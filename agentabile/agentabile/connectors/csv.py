"""
Connettore: CSV generico → Catalog canonico.

A differenza di WooCommerce (schema fisso, REST tipizzato), un CSV merchant
può avere intestazioni di colonna arbitrarie ("Prezzo", "Price", "SKU",
"Codice Articolo", ...). Il connettore quindi lavora in due fasi:

1. **Wizard di column-mapping** (`auto_detect_mapping`): tokenizza le
   intestazioni e le confronta contro un dizionario di alias per campo
   canonico (IT/EN), assegnando ogni colonna al campo con il punteggio di
   somiglianza (Jaccard sui token) più alto sopra soglia. Per ogni campo non
   rilevato con sufficiente confidenza viene generato un warning leggibile,
   così un umano può completare/correggere il mapping a mano.
2. **Applicazione del mapping** (`rows_to_catalog` / `load_catalog_from_csv`):
   il mapping (auto-rilevato, corretto a mano o ricaricato da un run
   precedente) viene applicato riga per riga per costruire il Catalog
   canonico. Il mapping stesso è una semplice `dict[str, str]`
   (campo canonico → intestazione colonna) serializzabile in JSON
   (`save_mapping`/`load_mapping`) così può essere salvato e riusato senza
   ripetere il wizard ad ogni import.

Raggruppamento in varianti: se il CSV ha una colonna riconosciuta come
`group_id` (es. "Item Group ID"), le righe con lo stesso valore diventano le
varianti di un unico Product; altrimenti ogni riga è un Product a variante
singola (id prodotto = id variante).
"""
from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

from agentabile.model import (
    Availability,
    AvailabilityStatus,
    Barcode,
    BarcodeType,
    Catalog,
    Category,
    Media,
    Money,
    Product,
    Variant,
)

# Campo canonico -> frasi alias (IT/EN) usate dal wizard per il riconoscimento.
FIELD_ALIASES: dict[str, list[str]] = {
    "variant_id": [
        "sku", "codice", "codice prodotto", "codice articolo", "id prodotto",
        "product id", "item id", "reference", "codice sku", "id",
    ],
    "group_id": [
        "item group id", "group id", "id gruppo", "codice modello",
        "parent id", "modello",
    ],
    "title": [
        "title", "nome prodotto", "titolo", "nome", "denominazione",
        "product name", "descrizione breve",
    ],
    "description": [
        "description", "descrizione", "descrizione lunga", "descrizione prodotto",
    ],
    "brand": ["brand", "marca", "produttore", "manufacturer"],
    "price": ["price", "prezzo", "prezzo vendita", "prezzo scontato", "sale price"],
    "list_price": [
        "list price", "prezzo pieno", "prezzo listino", "regular price",
        "msrp", "prezzo di listino",
    ],
    "currency": ["currency", "valuta"],
    "stock_quantity": [
        "quantity", "qty", "quantita", "giacenza", "stock", "quantita disponibile",
    ],
    "stock_status": ["stock status", "disponibilita", "availability", "stato disponibilita"],
    "category": ["category", "categoria", "categorie", "product category", "categoria prodotto"],
    "barcode": ["barcode", "ean", "gtin", "upc", "codice a barre", "codice ean"],
    "image_url": ["image", "immagine", "foto", "image url", "url immagine", "immagine url"],
    "url": ["url", "link", "pagina prodotto", "product url"],
}

# Senza questo campo una riga non produce una variante valida (Variant.id).
REQUIRED_FIELDS = {"variant_id"}
# Fortemente consigliati ma con fallback automatico (title -> variant_id).
RECOMMENDED_FIELDS = {"title"}

_MATCH_THRESHOLD = 0.5

_STOCK_STATUS_ALIASES: dict[AvailabilityStatus, list[str]] = {
    AvailabilityStatus.in_stock: ["instock", "in stock", "disponibile", "in magazzino", "si", "yes", "true", "1"],
    AvailabilityStatus.out_of_stock: ["outofstock", "out of stock", "esaurito", "non disponibile", "no", "false", "0"],
    AvailabilityStatus.preorder: ["preorder", "preordine", "prenotabile"],
    AvailabilityStatus.backorder: ["backorder", "ordinabile", "arretrato"],
    AvailabilityStatus.discontinued: ["discontinued", "fuori produzione", "cessato"],
}


# --------------------------------------------------------------------------
# Wizard di column-mapping
# --------------------------------------------------------------------------


def _tokenize(text: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    return frozenset(t for t in re.split(r"[^a-z0-9]+", normalized) if t)


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


@dataclass
class MappingSuggestion:
    """Esito del wizard per un singolo campo canonico (per audit/debug)."""

    field: str
    header: Optional[str]
    score: float


@dataclass
class WizardResult:
    mapping: dict[str, str] = field(default_factory=dict)
    suggestions: list[MappingSuggestion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def auto_detect_mapping(headers: list[str]) -> WizardResult:
    """Rileva automaticamente il mapping campo canonico -> intestazione CSV.

    Per ogni campo sceglie l'intestazione con la maggiore somiglianza
    (Jaccard sui token) tra i suoi alias noti, con assegnazione greedy
    (punteggio più alto prima) in modo che ogni colonna sia usata al più una
    volta. Sotto `_MATCH_THRESHOLD` il campo resta non mappato e viene
    generato un warning con il miglior candidato scartato, per permettere
    una correzione manuale.
    """
    header_tokens = {h: _tokenize(h) for h in headers}
    field_alias_tokens = {
        f: [_tokenize(alias) for alias in aliases] for f, aliases in FIELD_ALIASES.items()
    }

    scores: dict[tuple[str, str], float] = {}
    for f, alias_token_sets in field_alias_tokens.items():
        for header, htoks in header_tokens.items():
            best = max((_jaccard(htoks, a) for a in alias_token_sets), default=0.0)
            if best > 0:
                scores[(f, header)] = best

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    mapping: dict[str, str] = {}
    used_headers: set[str] = set()
    best_candidate: dict[str, tuple[str, float]] = {}
    for (f, header), score in ranked:
        best_candidate.setdefault(f, (header, score))
        if f in mapping or header in used_headers or score < _MATCH_THRESHOLD:
            continue
        mapping[f] = header
        used_headers.add(header)

    warnings: list[str] = []
    suggestions: list[MappingSuggestion] = []
    for f in FIELD_ALIASES:
        if f in mapping:
            suggestions.append(MappingSuggestion(f, mapping[f], scores[(f, mapping[f])]))
            continue
        candidate = best_candidate.get(f)
        if candidate is None:
            suggestions.append(MappingSuggestion(f, None, 0.0))
            if f in REQUIRED_FIELDS:
                warnings.append(f"campo '{f}' (obbligatorio) non rilevato in nessuna colonna")
            elif f in RECOMMENDED_FIELDS:
                warnings.append(
                    f"campo '{f}' non rilevato: verrà usato 'variant_id' come titolo (qualità dati ridotta)"
                )
            continue
        header, score = candidate
        suggestions.append(MappingSuggestion(f, None, score))
        warnings.append(
            f"campo '{f}': nessuna colonna con confidenza sufficiente "
            f"(miglior candidato '{header}', score {score:.2f}) — richiede mapping manuale"
        )

    return WizardResult(mapping=mapping, suggestions=suggestions, warnings=warnings)


def save_mapping(mapping: dict[str, str], path: str | Path) -> None:
    """Salva il mapping (auto-rilevato o corretto a mano) come JSON riusabile."""
    Path(path).write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")


def load_mapping(path: str | Path) -> dict[str, str]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Lettura CSV
# --------------------------------------------------------------------------


def read_csv_rows(
    path: str | Path, *, encoding: str = "utf-8-sig", delimiter: Optional[str] = None
) -> tuple[list[str], list[dict[str, str]]]:
    """Legge un CSV auto-rilevando il delimitatore (',', ';', '\\t', '|') se
    non specificato — i CSV merchant europei usano spesso ';' perché ',' è il
    separatore decimale in Excel."""
    text = Path(path).read_text(encoding=encoding)
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    headers = reader.fieldnames or []
    rows = list(reader)
    return list(headers), rows


def detect_mapping_from_csv(
    path: str | Path, *, encoding: str = "utf-8-sig", delimiter: Optional[str] = None
) -> WizardResult:
    headers, _rows = read_csv_rows(path, encoding=encoding, delimiter=delimiter)
    return auto_detect_mapping(headers)


# --------------------------------------------------------------------------
# Applicazione del mapping -> Catalog canonico
# --------------------------------------------------------------------------


def _get(row: dict[str, str], mapping: dict[str, str], f: str) -> Optional[str]:
    header = mapping.get(f)
    if not header:
        return None
    value = row.get(header)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _parse_decimal(raw: Optional[str]) -> Optional[Decimal]:
    """Euristica IT/EN: se sono presenti sia ',' che '.', l'ultimo dei due è
    il separatore decimale; se c'è solo ',', è decimale quando seguita da
    1-2 cifre finali (altrimenti è separatore delle migliaia)."""
    if raw is None:
        return None
    s = re.sub(r"[^\d,.\-]", "", raw.strip())
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = s.replace(",", ".") if len(tail) <= 2 else s.replace(",", "")
    try:
        amount = Decimal(s)
    except InvalidOperation:
        return None
    return amount if amount >= 0 else None


def _resolve_stock_status(raw: Optional[str], quantity: Optional[int]) -> AvailabilityStatus:
    if raw:
        tokens = _tokenize(raw)
        for status, aliases in _STOCK_STATUS_ALIASES.items():
            if any(_tokenize(alias) <= tokens for alias in aliases):
                return status
    if quantity is not None:
        return AvailabilityStatus.in_stock if quantity > 0 else AvailabilityStatus.out_of_stock
    return AvailabilityStatus.in_stock


def _row_categories(row: dict[str, str], mapping: dict[str, str]) -> list[Category]:
    raw = _get(row, mapping, "category")
    if not raw:
        return []
    if ">" in raw:
        # Notazione gerarchica (es. "Casa > Cucina > Pentole"): un solo valore.
        return [Category(value=raw, taxonomy="csv")]
    parts = [p.strip() for p in re.split(r"[;|,]", raw) if p.strip()]
    return [Category(value=p, taxonomy="csv") for p in parts]


def _row_media(row: dict[str, str], mapping: dict[str, str]) -> list[Media]:
    raw = _get(row, mapping, "image_url")
    if not raw:
        return []
    return [Media(url=u.strip()) for u in re.split(r"[|;]", raw) if u.strip()]


def _row_to_variant(
    row: dict[str, str], mapping: dict[str, str], variant_id: str,
    default_currency: str, warnings: list[str], row_num: int,
) -> Variant:
    currency = _get(row, mapping, "currency") or default_currency
    price = _parse_decimal(_get(row, mapping, "price"))
    list_price_raw = _parse_decimal(_get(row, mapping, "list_price"))

    price_money = Money(amount=price, currency=currency) if price is not None else None
    list_price_money: Optional[Money] = None
    if list_price_raw is not None:
        if price_money is None or list_price_raw > price:
            list_price_money = Money(amount=list_price_raw, currency=currency)

    quantity: Optional[int] = None
    qty_raw = _get(row, mapping, "stock_quantity")
    if qty_raw is not None:
        try:
            quantity = int(_parse_decimal(qty_raw) or 0)
        except (InvalidOperation, TypeError):
            warnings.append(f"riga {row_num} ({variant_id}): quantita '{qty_raw}' non numerica, ignorata")

    status = _resolve_stock_status(_get(row, mapping, "stock_status"), quantity)
    availability = Availability(
        available=status in (AvailabilityStatus.in_stock, AvailabilityStatus.backorder),
        status=status,
        quantity=quantity,
    )

    barcode_raw = _get(row, mapping, "barcode")
    barcodes = [Barcode(type=BarcodeType.gtin, value=barcode_raw)] if barcode_raw else []

    return Variant(
        id=variant_id,
        title=_get(row, mapping, "title") or variant_id,
        description_plain=_get(row, mapping, "description"),
        url=_get(row, mapping, "url"),
        barcodes=barcodes,
        price=price_money,
        list_price=list_price_money,
        availability=availability,
        media=_row_media(row, mapping),
    )


def rows_to_catalog(
    rows: list[dict[str, str]], mapping: dict[str, str], *, seller_name: str, default_currency: str = "EUR"
) -> tuple[Catalog, list[str]]:
    """Applica il mapping alle righe CSV e costruisce il Catalog canonico.

    Ritorna anche la lista di warning di qualità dati raccolti durante
    l'ingestion (righe scartate, quantità non numeriche, ...), utile per il
    futuro Agent-Readiness Score (roadmap punto 5).
    """
    warnings: list[str] = []
    groups: dict[str, list[Variant]] = {}
    group_repr_row: dict[str, dict[str, str]] = {}
    group_order: list[str] = []

    for i, row in enumerate(rows, start=1):
        variant_id = _get(row, mapping, "variant_id")
        if not variant_id:
            warnings.append(f"riga {i}: 'variant_id' mancante, riga scartata")
            continue
        variant = _row_to_variant(row, mapping, variant_id, default_currency, warnings, i)
        group_id = _get(row, mapping, "group_id") or variant_id
        if group_id not in groups:
            groups[group_id] = []
            group_repr_row[group_id] = row
            group_order.append(group_id)
        groups[group_id].append(variant)

    products: list[Product] = []
    for group_id in group_order:
        variants = groups[group_id]
        rep_row = group_repr_row[group_id]
        products.append(
            Product(
                id=group_id,
                title=_get(rep_row, mapping, "title") or variants[0].title,
                brand=_get(rep_row, mapping, "brand"),
                description_plain=_get(rep_row, mapping, "description"),
                url=variants[0].url,
                categories=_row_categories(rep_row, mapping),
                media=variants[0].media,
                variants=variants,
            )
        )

    catalog = Catalog(seller_name=seller_name, products=products)
    return catalog, warnings


def load_catalog_from_csv(
    path: str | Path,
    mapping: dict[str, str],
    *,
    seller_name: str,
    default_currency: str = "EUR",
    encoding: str = "utf-8-sig",
    delimiter: Optional[str] = None,
) -> tuple[Catalog, list[str]]:
    _headers, rows = read_csv_rows(path, encoding=encoding, delimiter=delimiter)
    return rows_to_catalog(rows, mapping, seller_name=seller_name, default_currency=default_currency)
