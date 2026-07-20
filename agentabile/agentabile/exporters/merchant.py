"""
Exporter: modello canonico → feed Google Merchant Center (XML e TSV).

Porta d'ingresso per UCP (Universal Commerce Protocol di Google): un feed
Merchant Center conforme è il prerequisito per la distribuzione via Google
Shopping/UCP. Granularità: come in ACP, un item del feed = una Variant
(un'offerta specifica), non un Product — i Product con più varianti
condividono `item_group_id`.

Attenzione alla convenzione dei prezzi, opposta a quella di ACP:
- Modello canonico: `price` = prezzo corrente pagato, `list_price` = prezzo
  pieno se il prodotto è in sconto.
- Merchant Center: `price` = prezzo pieno/di listino, `sale_price` = prezzo
  scontato attualmente applicato.
Vedi `_price_fields`.

Riferimento: https://support.google.com/merchants/answer/7052112
(attributi prodotto feed specification). Non essendoci uno schema ufficiale
vendorizzabile come per ACP, l'unica validazione automatica possibile è
strutturale (XML ben formato, colonne TSV coerenti) — vedi test_merchant_smoke.py.
"""
from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from typing import Any, Optional

from agentabile.model import (
    AvailabilityStatus,
    BarcodeType,
    Catalog,
    MediaType,
    Money,
    Product,
    Variant,
)

_G_NS = "http://base.google.com/ns/1.0"
ET.register_namespace("g", _G_NS)

# Ordine colonne TSV — segue l'ordine consigliato dalla product feed spec.
_TSV_COLUMNS = [
    "id", "title", "description", "link", "image_link", "additional_image_link",
    "availability", "price", "sale_price", "identifier_exists", "gtin", "mpn",
    "brand", "condition", "product_type", "google_product_category",
    "item_group_id", "color", "size", "material", "pattern", "shipping",
]

# Elementi XML che vivono nel namespace di default RSS, non in quello "g:".
_UNPREFIXED_XML_FIELDS = {"title", "description", "link"}

_AVAILABILITY_MAP = {
    AvailabilityStatus.in_stock: "in stock",
    AvailabilityStatus.out_of_stock: "out of stock",
    AvailabilityStatus.preorder: "preorder",
    AvailabilityStatus.backorder: "backorder",
    # Merchant Center non ha "discontinued": i prodotti fuori produzione
    # vanno rimossi dal feed o segnalati come esauriti.
    AvailabilityStatus.discontinued: "out of stock",
}

_CONDITION_MAP = {"new": "new", "used": "used", "refurbished": "refurbished"}

_VARIANT_ATTR_ALIASES: dict[str, set[str]] = {
    "color": {"color", "colore", "colour"},
    "size": {"size", "taglia", "formato", "misura"},
    "material": {"material", "materiale"},
    "pattern": {"pattern", "fantasia", "motivo"},
}


def _fmt_money(m: Money) -> str:
    return f"{m.amount:.2f} {m.currency}"


def _price_fields(variant: Variant) -> dict[str, str]:
    if variant.price is None:
        return {}
    if variant.list_price is not None:
        return {"price": _fmt_money(variant.list_price), "sale_price": _fmt_money(variant.price)}
    return {"price": _fmt_money(variant.price)}


def _identifier_fields(variant: Variant) -> dict[str, str]:
    gtin = next(
        (b.value for b in variant.barcodes
         if b.type in (BarcodeType.gtin, BarcodeType.ean, BarcodeType.upc, BarcodeType.isbn)),
        None,
    )
    mpn = next((b.value for b in variant.barcodes if b.type == BarcodeType.mpn), None)
    out: dict[str, str] = {}
    if gtin:
        out["gtin"] = gtin
    if mpn:
        out["mpn"] = mpn
    if not gtin and not mpn:
        out["identifier_exists"] = "no"
    return out


def _category_fields(product: Product) -> dict[str, str]:
    merchant_cats = [c.value for c in product.categories if c.taxonomy != "google_product_category"]
    google_cats = [c.value for c in product.categories if c.taxonomy == "google_product_category"]
    out: dict[str, str] = {}
    if merchant_cats:
        out["product_type"] = merchant_cats[0]
    if google_cats:
        out["google_product_category"] = google_cats[0]
    return out


def _variant_attribute_fields(variant: Variant) -> dict[str, str]:
    out: dict[str, str] = {}
    for opt in variant.options:
        name_norm = opt.name.strip().lower()
        for merchant_key, aliases in _VARIANT_ATTR_ALIASES.items():
            if name_norm in aliases and merchant_key not in out:
                out[merchant_key] = opt.value
    return out


def _shipping_field(variant: Variant) -> Optional[str]:
    """Solo la prima regola di spedizione della variante (MVP) nel formato
    breve `country:price` supportato dalla feed spec."""
    if not variant.shipping:
        return None
    s = variant.shipping[0]
    if not (s.country and s.price):
        return None
    return f"{s.country}:{_fmt_money(s.price)}"


def variant_to_merchant_row(product: Product, variant: Variant) -> dict[str, Any]:
    """Costruisce la riga feed (Merchant Center attribute -> valore) per una
    singola variante. I valori `additional_image_link` sono una lista, il
    resto stringhe — vedi i serializzatori per il trattamento specifico."""
    row: dict[str, Any] = {
        "id": variant.id,
        "title": variant.title or product.title,
        "condition": _CONDITION_MAP.get(variant.condition, "new"),
        "availability": _AVAILABILITY_MAP.get(variant.availability.status, "in stock"),
    }
    description = variant.description_plain or product.description_plain
    if description:
        row["description"] = description
    link = variant.url or product.url
    if link:
        row["link"] = str(link)

    images = [m for m in (variant.media or product.media) if m.type == MediaType.image]
    if images:
        row["image_link"] = str(images[0].url)
        if len(images) > 1:
            row["additional_image_link"] = [str(m.url) for m in images[1:11]]

    if product.brand:
        row["brand"] = product.brand

    row.update(_identifier_fields(variant))
    row.update(_price_fields(variant))
    row.update(_category_fields(product))

    if len(product.variants) > 1:
        row["item_group_id"] = product.id
    row.update(_variant_attribute_fields(variant))

    shipping = _shipping_field(variant)
    if shipping:
        row["shipping"] = shipping

    return row


def catalog_to_merchant_rows(catalog: Catalog) -> list[dict[str, Any]]:
    """Un item per Variant, granularità coerente con l'export ACP."""
    return [
        variant_to_merchant_row(product, variant)
        for product in catalog.products
        for variant in product.variants
    ]


def _tsv_escape(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def catalog_to_merchant_tsv(catalog: Catalog) -> str:
    rows = catalog_to_merchant_rows(catalog)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n")
    writer.writerow(_TSV_COLUMNS)
    for row in rows:
        line = []
        for col in _TSV_COLUMNS:
            value = row.get(col, "")
            if isinstance(value, list):
                value = ", ".join(value)
            line.append(_tsv_escape(str(value)) if value else "")
        writer.writerow(line)
    return buf.getvalue()


def catalog_to_merchant_xml(catalog: Catalog) -> str:
    rows = catalog_to_merchant_rows(catalog)
    rss = ET.Element("rss", attrib={"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = catalog.seller_name
    if catalog.seller_url:
        ET.SubElement(channel, "link").text = str(catalog.seller_url)
    ET.SubElement(channel, "description").text = f"Feed prodotti {catalog.seller_name}"

    for row in rows:
        item = ET.SubElement(channel, "item")
        for col in _TSV_COLUMNS:
            value = row.get(col)
            if not value:
                continue
            tag = col if col in _UNPREFIXED_XML_FIELDS else f"{{{_G_NS}}}{col}"
            if col == "additional_image_link" and isinstance(value, list):
                for url in value:
                    ET.SubElement(item, f"{{{_G_NS}}}additional_image_link").text = url
                continue
            ET.SubElement(item, tag).text = str(value)

    return ET.tostring(rss, encoding="unicode", xml_declaration=True)
