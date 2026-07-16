"""Smoke test del connettore WooCommerce contro un'istanza reale (locale o remota).

A differenza di test_woocommerce_mapping.py (offline, risposte HTTP simulate),
questo script parla davvero con `GET /wp-json/wc/v3/products` di un'istanza
WooCommerce, scarica il catalogo, lo normalizza nel modello canonico e lo
esporta/valida in ACP — end-to-end contro dati reali.

Uso (esempio con l'istanza WooCommerce locale via Docker usata in sviluppo):

    WC_URL=http://localhost:8089 \
    WC_CONSUMER_KEY=ck_... \
    WC_CONSUMER_SECRET=cs_... \
    python3 tests/test_woocommerce_smoke.py

Se le variabili d'ambiente non sono impostate, il test viene saltato (exit 0)
con un messaggio esplicativo, per non rompere run automatizzate senza
un'istanza Woo disponibile.
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentready.connectors.woocommerce import fetch_catalog
from agentready.exporters.acp import catalog_to_acp
from agentready.validate import validate_acp_products

WC_URL = os.environ.get("WC_URL")
WC_CONSUMER_KEY = os.environ.get("WC_CONSUMER_KEY")
WC_CONSUMER_SECRET = os.environ.get("WC_CONSUMER_SECRET")
WC_SELLER_NAME = os.environ.get("WC_SELLER_NAME", "WooCommerce Test Shop")
WC_CURRENCY = os.environ.get("WC_CURRENCY", "EUR")


if __name__ == "__main__":
    if not (WC_URL and WC_CONSUMER_KEY and WC_CONSUMER_SECRET):
        print(
            "SKIP: imposta WC_URL, WC_CONSUMER_KEY, WC_CONSUMER_SECRET per testare "
            "contro un'istanza WooCommerce reale (locale o remota)."
        )
        sys.exit(0)

    print(f"--- Connessione a {WC_URL} ---")
    cat = fetch_catalog(
        WC_URL,
        WC_CONSUMER_KEY,
        WC_CONSUMER_SECRET,
        seller_name=WC_SELLER_NAME,
        currency=WC_CURRENCY,
    )
    print(f"Prodotti canonici trovati: {len(cat.products)}")
    for p in cat.products:
        print(f"  • {p.id} — {p.title} ({len(p.variants)} varianti)")

    if not cat.products:
        print("ATTENZIONE: nessun prodotto trovato — verifica dati demo sull'istanza.")
        sys.exit(1)

    acp = catalog_to_acp(cat)
    errors = validate_acp_products(acp)
    print(json.dumps(acp, indent=2, ensure_ascii=False))
    print("\n--- VALIDAZIONE SCHEMA UFFICIALE ACP 2026-04-17 (istanza WooCommerce reale) ---")
    if errors:
        print(f"FALLITA: {len(errors)} errori")
        for e in errors:
            print(" •", e)
        sys.exit(1)
    print("OK: catalogo WooCommerce (live) -> canonico -> ACP conforme allo schema ufficiale.")
