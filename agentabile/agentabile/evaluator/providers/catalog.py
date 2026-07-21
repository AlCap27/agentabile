"""
CatalogProvider: adapter Catalog canonico -> list[Evidence] per la rubrica
DQ-* (data quality). Vedi EVALUATOR_DESIGN.md §1.

Questi non sono requisiti AR-* (quelli sono verificati dal SiteProvider):
sono la rubrica "quality" già esistente in `agentabile.score`, riportata qui
come check pesati che producono Evidence invece di Issue direttamente.
`agentabile.score` resta l'unico modulo pubblico consumato dal resto del
progetto (CLI, plugin non-Python): qui vive solo la logica di check,
riusata da `score.py` per costruire il report leggibile.

Vincolo di design: `score_product`/`score_catalog`/`format_report` devono
restare a output numerico identico a prima del refactoring (stessi pesi,
stesso `_MAX_POINTS` implicito = somma dei pesi sotto = 110).
"""
from __future__ import annotations

import re
from typing import Callable, NamedTuple, Optional

from agentabile.evaluator.evidence import Evidence, Outcome, RubricItem
from agentabile.model import Catalog, Product

_TAG_RE = re.compile(r"<[^>]+>")


def _plain_len(text: str | None) -> int:
    if not text:
        return 0
    return len(_TAG_RE.sub(" ", text).strip())


class DQCheck(NamedTuple):
    id: str
    field: str
    severity: str  # "error" | "warning" | "info"
    weight: int
    check: Callable[[Product], Optional[str]]  # ritorna il messaggio se fallisce, None se ok


def _check_title(p: Product) -> Optional[str]:
    if not p.title or len(p.title.strip()) < 3:
        return "Titolo mancante o troppo corto per essere utile a un agente"
    return None


def _check_description(p: Product) -> Optional[str]:
    if max(_plain_len(p.description_plain), _plain_len(p.description_html)) < 20:
        return "Descrizione assente o troppo breve (<20 caratteri): poco contesto per un agente"
    return None


def _check_brand(p: Product) -> Optional[str]:
    if not p.brand:
        return "Brand mancante — utile per matching cross-piattaforma e fiducia dell'agente"
    return None


def _check_category(p: Product) -> Optional[str]:
    if not p.categories:
        return "Nessuna categoria — l'agente non può posizionare il prodotto in una ricerca per categoria"
    return None


def _check_media(p: Product) -> Optional[str]:
    if not p.media and not any(v.media for v in p.variants):
        return "Nessuna immagine su prodotto o varianti — molte superfici agent (ACP, Google) la richiedono"
    return None


def _check_url(p: Product) -> Optional[str]:
    if not p.url and not (p.variants and all(v.url for v in p.variants)):
        return "Nessun link alla pagina prodotto — l'agente non può indirizzare l'utente all'acquisto"
    return None


def _check_price(p: Product) -> Optional[str]:
    unpriced = [v.id for v in p.variants if v.price is None]
    if unpriced:
        return (
            f"{len(unpriced)}/{len(p.variants)} varianti senza prezzo: un agente non può proporre "
            f"un acquisto ({', '.join(unpriced[:3])}{'...' if len(unpriced) > 3 else ''})"
        )
    return None


def _check_barcode(p: Product) -> Optional[str]:
    missing = [v.id for v in p.variants if not v.barcodes]
    if missing:
        return f"{len(missing)}/{len(p.variants)} varianti senza barcode (GTIN/EAN/UPC) — consigliato per il matching cross-piattaforma"
    return None


def _check_variant_options(p: Product) -> Optional[str]:
    if len(p.variants) > 1:
        missing = [v.id for v in p.variants if not v.options]
        if missing:
            return f"{len(missing)}/{len(p.variants)} varianti senza opzioni (es. colore/taglia): l'agente non può distinguerle o spiegarne la differenza"
    return None


def _check_availability_quantity(p: Product) -> Optional[str]:
    incomplete = [v.id for v in p.variants if v.availability.status.value == "in_stock" and v.availability.quantity is None]
    if incomplete:
        return f"{len(incomplete)}/{len(p.variants)} varianti 'in_stock' senza quantità: l'agente non può rispondere a 'quante ne avete disponibili'"
    return None


DQ_CHECKS: list[DQCheck] = [
    DQCheck("DQ-title", "title", "error", 15, _check_title),
    DQCheck("DQ-description", "description", "warning", 15, _check_description),
    DQCheck("DQ-brand", "brand", "info", 5, _check_brand),
    DQCheck("DQ-categories", "categories", "warning", 10, _check_category),
    DQCheck("DQ-media", "media", "error", 15, _check_media),
    DQCheck("DQ-url", "url", "warning", 10, _check_url),
    DQCheck("DQ-price", "price", "error", 20, _check_price),
    DQCheck("DQ-barcode", "barcode", "info", 5, _check_barcode),
    DQCheck("DQ-variant-options", "variant_options", "warning", 10, _check_variant_options),
    DQCheck("DQ-availability", "availability", "info", 5, _check_availability_quantity),
]

DQ_RUBRIC: list[RubricItem] = [
    RubricItem(id=c.id, name=c.field, axis="quality", weight=c.weight, strength=None)
    for c in DQ_CHECKS
]


def evaluate_product(p: Product) -> list[Evidence]:
    evidences = []
    for c in DQ_CHECKS:
        message = c.check(p)
        if message is None:
            evidences.append(Evidence(
                requirement_id=c.id, outcome=Outcome.PASS, detail="ok",
                observed={"field": c.field, "severity": c.severity, "weight": str(c.weight)},
            ))
        else:
            evidences.append(Evidence(
                requirement_id=c.id, outcome=Outcome.FAIL, detail=message,
                observed={"field": c.field, "severity": c.severity, "weight": str(c.weight)},
            ))
    return evidences


def evaluate_catalog(catalog: Catalog) -> dict[str, list[Evidence]]:
    """Evidenze per prodotto, chiavate per product_id (l'engine punteggia un
    prodotto alla volta: il punteggio di catalogo è una media, non una
    somma di pesi cross-prodotto)."""
    return {p.id: evaluate_product(p) for p in catalog.products}
