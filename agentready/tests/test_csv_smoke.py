"""Smoke test del connettore CSV: wizard di mapping, mapping salvabile in
JSON, ingestion -> Catalog canonico -> ACP -> validazione schema ufficiale.

Interamente offline (nessuna rete, nessun servizio esterno): un CSV di
esempio con intestazioni italiane realistiche, generato in memoria.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentready.connectors.csv import (
    auto_detect_mapping,
    load_mapping,
    read_csv_rows,
    rows_to_catalog,
    save_mapping,
)
from agentready.exporters.acp import catalog_to_acp
from agentready.validate import validate_acp_products

CSV_TEXT = (
    "Codice Articolo;Item Group ID;Nome Prodotto;Descrizione;Marca;"
    "Prezzo;Prezzo di Listino;Valuta;Quantita;Disponibilita;Categoria;"
    "Codice EAN;Immagine;URL;Colonna Sconosciuta\n"
    "TAZZA-001;;Tazza da Caffe;Tazza in ceramica fatta a mano.;CasaItalia;"
    "9,90;12,90;EUR;42;Disponibile;Casa > Cucina > Tazze;"
    "8001234500019;https://esempio-shop.it/img/tazza.jpg;https://esempio-shop.it/tazza;xxx\n"
    "MAGLIETTA-LOGO-S;MAGLIETTA-LOGO;Maglietta Logo - S;Maglietta 100% cotone.;;"
    "19,90;;EUR;10;Disponibile;Abbigliamento;;;https://esempio-shop.it/maglietta-s;yyy\n"
    "MAGLIETTA-LOGO-M;MAGLIETTA-LOGO;Maglietta Logo - M;Maglietta 100% cotone.;;"
    "19,90;22,90;EUR;0;Esaurito;Abbigliamento;;;https://esempio-shop.it/maglietta-m;zzz\n"
)


def _write_temp_csv() -> Path:
    tmp_dir = Path(tempfile.mkdtemp(prefix="agentready-csv-smoke-"))
    path = tmp_dir / "catalogo_demo.csv"
    path.write_text(CSV_TEXT, encoding="utf-8-sig")
    return path


if __name__ == "__main__":
    csv_path = _write_temp_csv()
    mapping_path = csv_path.with_suffix(".mapping.json")

    headers, rows = read_csv_rows(csv_path)
    print(f"Intestazioni rilevate ({len(headers)}): {headers}")

    result = auto_detect_mapping(headers)
    print("\n--- WIZARD: mapping auto-rilevato ---")
    print(json.dumps(result.mapping, indent=2, ensure_ascii=False))
    print("--- WIZARD: warning ---")
    for w in result.warnings:
        print(" •", w)

    expected_mapping = {
        "variant_id": "Codice Articolo",
        "group_id": "Item Group ID",
        "title": "Nome Prodotto",
        "description": "Descrizione",
        "brand": "Marca",
        "price": "Prezzo",
        "list_price": "Prezzo di Listino",
        "currency": "Valuta",
        "stock_quantity": "Quantita",
        "stock_status": "Disponibilita",
        "category": "Categoria",
        "barcode": "Codice EAN",
        "image_url": "Immagine",
        "url": "URL",
    }
    for field, header in expected_mapping.items():
        got = result.mapping.get(field)
        assert got == header, f"campo '{field}': atteso '{header}', ottenuto '{got}'"
    assert "Colonna Sconosciuta" not in result.mapping.values()
    assert not result.warnings, f"nessun warning atteso con intestazioni pulite, trovati: {result.warnings}"

    # Mapping salvabile/ricaricabile in JSON (persistenza tra run successivi).
    save_mapping(result.mapping, mapping_path)
    reloaded_mapping = load_mapping(mapping_path)
    assert reloaded_mapping == result.mapping

    cat, ingest_warnings = rows_to_catalog(rows, reloaded_mapping, seller_name="Esempio Shop SRL")
    print(f"\nProdotti canonici: {len(cat.products)}  |  warning ingestion: {ingest_warnings}")
    assert not ingest_warnings
    assert len(cat.products) == 2

    tazza = next(p for p in cat.products if p.id == "TAZZA-001")
    assert tazza.brand == "CasaItalia"
    assert len(tazza.variants) == 1
    assert str(tazza.variants[0].price.amount) == "9.90"
    assert str(tazza.variants[0].list_price.amount) == "12.90"
    assert tazza.variants[0].availability.status.value == "in_stock"
    assert tazza.variants[0].barcodes[0].value == "8001234500019"
    assert tazza.categories[0].value == "Casa > Cucina > Tazze"

    maglietta = next(p for p in cat.products if p.id == "MAGLIETTA-LOGO")
    assert len(maglietta.variants) == 2
    taglia_m = next(v for v in maglietta.variants if v.id == "MAGLIETTA-LOGO-M")
    assert taglia_m.availability.available is False
    assert str(taglia_m.list_price.amount) == "22.90"

    acp = catalog_to_acp(cat)
    errors = validate_acp_products(acp)
    print("\n--- VALIDAZIONE SCHEMA UFFICIALE ACP 2026-04-17 (via connettore CSV) ---")
    if errors:
        print(f"FALLITA: {len(errors)} errori")
        for e in errors:
            print(" •", e)
        sys.exit(1)
    print("OK: catalogo CSV -> canonico -> ACP conforme allo schema ufficiale.")

    # --- Caso 2: intestazioni ambigue/minime -> il wizard deve avvisare, non fallire in silenzio.
    minimal_headers = ["Codice", "Note interne"]
    minimal_result = auto_detect_mapping(minimal_headers)
    assert minimal_result.mapping.get("variant_id") == "Codice"
    assert "title" not in minimal_result.mapping
    assert any("title" in w for w in minimal_result.warnings), minimal_result.warnings
    print("\nOK: wizard segnala correttamente i campi mancanti su intestazioni minime.")
