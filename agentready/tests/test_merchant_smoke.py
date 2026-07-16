"""Smoke test dell'exporter Google Merchant Center (XML/TSV).

Non esiste uno schema ufficiale vendorizzabile come per ACP: la spec di
Google è documentazione prosa, non un JSON Schema pubblicato. La
validazione qui è quindi strutturale — XML ben formato via
xml.etree.ElementTree, TSV riparsato via csv.DictReader — più asserzioni
puntuali sui valori più delicati (inversione price/sale_price rispetto ad
ACP, availability con spazi non underscore, item_group_id sulle varianti).
"""
import csv
import io
import sys
import xml.etree.ElementTree as ET
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentready.model import (
    Availability, AvailabilityStatus, Barcode, BarcodeType, Catalog,
    Category, Media, Money, Product, Shipping, Variant, VariantOption,
)
from agentready.exporters.merchant import (
    _G_NS,
    catalog_to_merchant_rows,
    catalog_to_merchant_tsv,
    catalog_to_merchant_xml,
)


def build_catalog() -> Catalog:
    moka = Product(
        id="MOKA-CLASSIC",
        title="Caffettiera Moka Classica",
        brand="CasaItalia",
        description_plain="Caffettiera moka in alluminio, made in Italy.",
        url="https://example-shop.it/prodotti/moka-classica",
        categories=[
            Category(value="Casa > Cucina > Caffettiere", taxonomy="merchant"),
            Category(value="503", taxonomy="google_product_category"),
        ],
        media=[Media(url="https://example-shop.it/img/moka.jpg", alt_text="Moka 3 tazze")],
        variants=[
            Variant(
                id="MOKA-3TZ",
                title="Moka Classica — 3 tazze",
                barcodes=[Barcode(type=BarcodeType.ean, value="8001234567890")],
                price=Money(amount=Decimal("19.90"), currency="EUR"),
                list_price=Money(amount=Decimal("24.90"), currency="EUR"),
                options=[VariantOption(name="Formato", value="3 tazze")],
                shipping=[Shipping(country="IT", price=Money(amount=Decimal("4.99"), currency="EUR"))],
            ),
            Variant(
                id="MOKA-6TZ",
                title="Moka Classica — 6 tazze",
                price=Money(amount=Decimal("27.50"), currency="EUR"),
                availability=Availability(available=False, status=AvailabilityStatus.out_of_stock),
                options=[VariantOption(name="Formato", value="6 tazze")],
            ),
        ],
    )
    maglietta = Product(
        id="MAGLIETTA-LOGO",
        title="Maglietta Logo",
        variants=[
            Variant(
                id="MAGLIETTA-LOGO-M",
                title="Maglietta Logo — M",
                price=Money(amount=Decimal("19.90"), currency="EUR"),
                options=[VariantOption(name="Colore", value="Blu"), VariantOption(name="Taglia", value="M")],
                # Nessun barcode -> identifier_exists deve risultare "no".
            )
        ],
    )
    return Catalog(seller_name="Example Shop SRL", seller_url="https://example-shop.it",
                    products=[moka, maglietta])


if __name__ == "__main__":
    cat = build_catalog()
    rows = catalog_to_merchant_rows(cat)
    assert len(rows) == 3, f"attese 3 righe (varianti), trovate {len(rows)}"

    by_id = {r["id"]: r for r in rows}

    tre_tazze = by_id["MOKA-3TZ"]
    # Inversione rispetto ad ACP: price = prezzo pieno, sale_price = prezzo scontato.
    assert tre_tazze["price"] == "24.90 EUR", tre_tazze["price"]
    assert tre_tazze["sale_price"] == "19.90 EUR", tre_tazze["sale_price"]
    assert tre_tazze["gtin"] == "8001234567890"
    assert tre_tazze["item_group_id"] == "MOKA-CLASSIC"
    assert tre_tazze["availability"] == "in stock"
    assert tre_tazze["product_type"] == "Casa > Cucina > Caffettiere"
    assert tre_tazze["google_product_category"] == "503"
    assert tre_tazze["shipping"] == "IT:4.99 EUR"
    assert tre_tazze["brand"] == "CasaItalia"

    sei_tazze = by_id["MOKA-6TZ"]
    assert sei_tazze["availability"] == "out of stock"
    assert "sale_price" not in sei_tazze  # nessuno sconto -> solo price
    assert sei_tazze["price"] == "27.50 EUR"

    maglietta_m = by_id["MAGLIETTA-LOGO-M"]
    assert maglietta_m["identifier_exists"] == "no"
    assert maglietta_m["color"] == "Blu"
    assert maglietta_m["size"] == "M"
    assert "item_group_id" not in maglietta_m  # unica variante del prodotto

    # --- TSV ---
    tsv_text = catalog_to_merchant_tsv(cat)
    reader = csv.DictReader(io.StringIO(tsv_text), delimiter="\t")
    tsv_rows = list(reader)
    assert len(tsv_rows) == 3
    tsv_by_id = {r["id"]: r for r in tsv_rows}
    assert tsv_by_id["MOKA-3TZ"]["sale_price"] == "19.90 EUR"
    assert tsv_by_id["MOKA-3TZ"]["price"] == "24.90 EUR"
    assert tsv_by_id["MAGLIETTA-LOGO-M"]["identifier_exists"] == "no"
    print(f"TSV: {len(tsv_rows)} righe, {len(reader.fieldnames)} colonne — OK")

    # --- XML ---
    xml_text = catalog_to_merchant_xml(cat)
    root = ET.fromstring(xml_text)
    assert root.tag == "rss"
    items = root.findall("./channel/item")
    assert len(items) == 3

    def g(item, field):
        return item.findtext(f"{{{_G_NS}}}{field}")

    xml_by_id = {g(item, "id"): item for item in items}
    tre_tazze_xml = xml_by_id["MOKA-3TZ"]
    assert g(tre_tazze_xml, "price") == "24.90 EUR"
    assert g(tre_tazze_xml, "sale_price") == "19.90 EUR"
    assert tre_tazze_xml.findtext("title") == "Moka Classica — 3 tazze"  # non prefissato g:
    assert g(tre_tazze_xml, "item_group_id") == "MOKA-CLASSIC"
    print(f"XML: {len(items)} item ben formati — OK")

    print("\nOK: exporter Google Merchant Center (TSV + XML) coerente col modello canonico.")
