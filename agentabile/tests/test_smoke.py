"""Smoke test: costruisce un catalogo canonico realistico, esporta in ACP,
valida contro lo schema ufficiale 2026-04-17."""
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentabile.model import (
    Availability, AvailabilityStatus, Barcode, BarcodeType, Catalog,
    Category, Media, Money, Product, Variant, VariantOption,
)
from agentabile.exporters.acp import catalog_to_acp
from agentabile.validate import validate_acp_products


def build_catalog() -> Catalog:
    moka = Product(
        id="MOKA-CLASSIC",
        title="Caffettiera Moka Classica",
        brand="CasaItalia",
        description_plain="Caffettiera moka in alluminio, made in Italy.",
        url="https://example-shop.it/prodotti/moka-classica",
        categories=[Category(value="Casa > Cucina > Caffettiere", taxonomy="merchant")],
        media=[Media(url="https://example-shop.it/img/moka.jpg", alt_text="Moka 3 tazze")],
        variants=[
            Variant(
                id="MOKA-3TZ",
                title="Moka Classica — 3 tazze",
                barcodes=[Barcode(type=BarcodeType.ean, value="8001234567890")],
                price=Money(amount=Decimal("19.90"), currency="EUR"),
                list_price=Money(amount=Decimal("24.90"), currency="EUR"),
                options=[VariantOption(name="Formato", value="3 tazze")],
            ),
            Variant(
                id="MOKA-6TZ",
                title="Moka Classica — 6 tazze",
                price=Money(amount=Decimal("27.50"), currency="EUR"),
                availability=Availability(available=False,
                                          status=AvailabilityStatus.out_of_stock),
                options=[VariantOption(name="Formato", value="6 tazze")],
            ),
        ],
    )
    return Catalog(seller_name="Example Shop SRL",
                   seller_url="https://example-shop.it", products=[moka])


if __name__ == "__main__":
    cat = build_catalog()
    acp = catalog_to_acp(cat)
    errors = validate_acp_products(acp)
    print(json.dumps(acp, indent=2, ensure_ascii=False))
    print("\n--- VALIDAZIONE SCHEMA UFFICIALE ACP 2026-04-17 ---")
    if errors:
        print(f"FALLITA: {len(errors)} errori")
        for e in errors:
            print(" •", e)
        sys.exit(1)
    print("OK: feed conforme allo schema ufficiale.")
