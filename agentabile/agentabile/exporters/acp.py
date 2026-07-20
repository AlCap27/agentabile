"""
Exporter: modello canonico → ACP feed (spec 2026-04-17).

Produce dizionari conformi a $defs/Product dello schema.feed.json ufficiale.
Regole chiave della spec:
- Product richiede: id, variants. Variant richiede: id, title.
- I prezzi sono interi in minor units ISO 4217 (EUR 19.90 → 1990).
- additionalProperties: false ovunque → emettiamo SOLO campi previsti.
"""
from __future__ import annotations

from typing import Any

from agentabile.model import Catalog, Media, Product, Variant

# Mappa barcode canonico → tipi barcode ACP (stringa libera nella spec,
# ma usiamo etichette convenzionali riconosciute dagli agent surface)
_BARCODE_TYPE = {"gtin": "gtin", "ean": "ean", "upc": "upc", "isbn": "isbn", "mpn": "mpn"}


def _media(m: Media) -> dict[str, Any]:
    out: dict[str, Any] = {"type": m.type.value, "url": str(m.url)}
    if m.alt_text:
        out["alt_text"] = m.alt_text
    return out


def _variant(v: Variant, seller_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {"id": v.id, "title": v.title}
    if v.description_plain:
        out["description"] = {"plain": v.description_plain}
    if v.url:
        out["url"] = str(v.url)
    if v.barcodes:
        out["barcodes"] = [
            {"type": _BARCODE_TYPE[b.type.value], "value": b.value} for b in v.barcodes
        ]
    if v.price:
        out["price"] = {"amount": v.price.minor_units(), "currency": v.price.currency}
    if v.list_price:
        out["list_price"] = {
            "amount": v.list_price.minor_units(),
            "currency": v.list_price.currency,
        }
    out["availability"] = {
        "available": v.availability.available,
        "status": v.availability.status.value,
    }
    if v.condition:
        out["condition"] = [v.condition]
    if v.options:
        out["variant_options"] = [{"name": o.name, "value": o.value} for o in v.options]
    if v.media:
        out["media"] = [_media(m) for m in v.media]
    out["seller"] = {"name": seller_name}
    return out


def product_to_acp(p: Product, seller_name: str) -> dict[str, Any]:
    out: dict[str, Any] = {"id": p.id, "variants": [_variant(v, seller_name) for v in p.variants]}
    if p.title:
        out["title"] = p.title
    if p.description_plain or p.description_html:
        desc: dict[str, str] = {}
        if p.description_plain:
            desc["plain"] = p.description_plain
        if p.description_html:
            desc["html"] = p.description_html
        # Nella spec Product.description è un $ref a Description
        out["description"] = desc
    if p.url:
        out["url"] = str(p.url)
    if p.media:
        out["media"] = [_media(m) for m in p.media]
    # NB: categories/brand vivono a livello Variant nella spec ACP feed;
    # le categorie canoniche di prodotto vengono propagate alle varianti.
    if p.categories:
        cats = [
            {k: v for k, v in {"value": c.value, "taxonomy": c.taxonomy}.items() if v}
            for c in p.categories
        ]
        for var in out["variants"]:
            var["categories"] = cats
    return out


def catalog_to_acp(cat: Catalog) -> list[dict[str, Any]]:
    """Restituisce la lista di prodotti ACP pronta per UpsertProductsRequest/feed file."""
    return [product_to_acp(p, cat.seller_name) for p in cat.products]
