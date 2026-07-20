"""Smoke test dell'Agent-Readiness Score: un catalogo con un prodotto
"da manuale" (tutti i campi compilati) e uno scadente (mancano quasi tutti
i segnali che servono a un agente) deve produrre punteggi nettamente
diversi, un summary coerente e un report leggibile."""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentabile.model import (
    Availability, AvailabilityStatus, Barcode, BarcodeType, Catalog,
    Category, Media, Money, Product, Variant, VariantOption,
)
from agentabile.score import format_report, score_catalog, score_product


def build_catalog() -> Catalog:
    ottimo = Product(
        id="MOKA-CLASSIC",
        title="Caffettiera Moka Classica",
        brand="CasaItalia",
        description_plain="Caffettiera moka in alluminio, made in Italy, capacità 3 tazze.",
        url="https://example-shop.it/prodotti/moka-classica",
        categories=[Category(value="Casa > Cucina > Caffettiere", taxonomy="merchant")],
        media=[Media(url="https://example-shop.it/img/moka.jpg")],
        variants=[
            Variant(
                id="MOKA-3TZ", title="Moka Classica — 3 tazze",
                barcodes=[Barcode(type=BarcodeType.ean, value="8001234567890")],
                price=Money(amount=Decimal("19.90"), currency="EUR"),
                availability=Availability(available=True, status=AvailabilityStatus.in_stock, quantity=42),
                options=[VariantOption(name="Formato", value="3 tazze")],
            ),
        ],
    )
    scadente = Product(
        id="MISTERO-001",
        title="ok",
        variants=[
            Variant(id="MISTERO-001-A", title="ok"),
            Variant(id="MISTERO-001-B", title="ok"),
        ],
    )
    return Catalog(seller_name="Example Shop SRL", products=[ottimo, scadente])


if __name__ == "__main__":
    cat = build_catalog()

    ottimo_score = score_product(cat.products[0])
    assert ottimo_score.score == 100, (ottimo_score.score, ottimo_score.issues)
    assert ottimo_score.issues == []

    scadente_score = score_product(cat.products[1])
    assert scadente_score.score < 40, (scadente_score.score, scadente_score.issues)
    fields_with_issues = {i.field for i in scadente_score.issues}
    assert fields_with_issues == {
        "title", "description", "brand", "categories", "media", "url",
        "price", "barcode", "variant_options", "availability",
    }, fields_with_issues

    report = score_catalog(cat)
    assert report.product_count == 2
    assert 0 < report.overall_score < 100
    assert report.summary["price"] == 1  # solo il prodotto scadente ha varianti senza prezzo
    assert report.summary["media"] == 1

    text = format_report(report)
    print(text)
    assert "Example Shop SRL" in text
    assert "MISTERO-001" in text
    assert "MOKA-CLASSIC" not in text  # nessun problema -> non compare nel dettaglio

    print("\nOK: Agent-Readiness Score discrimina correttamente qualità alta/bassa e produce un report leggibile.")
