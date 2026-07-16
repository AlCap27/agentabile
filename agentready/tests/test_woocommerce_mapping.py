"""Test di mapping del connettore WooCommerce, offline (nessuna rete).

Simula le risposte REST v3 di un'istanza WooCommerce reale (payload ridotti
ma realistici, un prodotto simple + un prodotto variable con 2 varianti) e
verifica end-to-end: WooCommerce → Catalog canonico → ACP → validazione
schema ufficiale.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentready.connectors.woocommerce import WooCommerceClient, fetch_catalog
from agentready.exporters.acp import catalog_to_acp
from agentready.validate import validate_acp_products

PRODUCTS_PAGE_1 = [
    {
        "id": 101,
        "name": "Tazza da Caffè",
        "type": "simple",
        "status": "publish",
        "permalink": "https://esempio-shop.local/prodotto/tazza-da-caffe/",
        "sku": "TAZZA-001",
        "description": "<p>Tazza in ceramica <strong>fatta a mano</strong>.</p>",
        "short_description": "<p>Tazza in ceramica, 250ml.</p>",
        "price": "9.90",
        "regular_price": "12.90",
        "sale_price": "9.90",
        "stock_status": "instock",
        "stock_quantity": 42,
        "global_unique_id": "8001234500019",
        "categories": [{"id": 15, "name": "Casa > Cucina > Tazze", "slug": "tazze"}],
        "images": [{"id": 1, "src": "https://esempio-shop.local/wp-content/uploads/tazza.jpg", "alt": "Tazza"}],
        "attributes": [{"id": 1, "name": "Materiale", "options": ["Ceramica"], "variation": False}],
        "brands": [{"id": 3, "name": "CasaItalia", "slug": "casaitalia"}],
    },
    {
        "id": 102,
        "name": "Maglietta Logo",
        "type": "variable",
        "status": "publish",
        "permalink": "https://esempio-shop.local/prodotto/maglietta-logo/",
        "sku": "MAGLIETTA-LOGO",
        "description": "<p>Maglietta 100% cotone.</p>",
        "short_description": "<p>Maglietta con logo.</p>",
        "price": "",
        "regular_price": "",
        "stock_status": "instock",
        "categories": [{"id": 20, "name": "Abbigliamento > T-shirt", "slug": "t-shirt"}],
        "images": [{"id": 2, "src": "https://esempio-shop.local/wp-content/uploads/maglietta.jpg", "alt": "Maglietta"}],
        "attributes": [{"id": 2, "name": "Taglia", "options": ["S", "M"], "variation": True}],
    },
]

VARIATIONS_102 = [
    {
        "id": 201,
        "sku": "MAGLIETTA-LOGO-S",
        "permalink": "https://esempio-shop.local/prodotto/maglietta-logo/?attribute_taglia=s",
        "description": "",
        "price": "19.90",
        "regular_price": "19.90",
        "stock_status": "instock",
        "stock_quantity": 10,
        "attributes": [{"id": 2, "name": "Taglia", "option": "S"}],
        "image": {"id": 3, "src": "https://esempio-shop.local/wp-content/uploads/maglietta-s.jpg", "alt": "Taglia S"},
        "global_unique_id": "",
    },
    {
        "id": 202,
        "sku": "MAGLIETTA-LOGO-M",
        "permalink": "https://esempio-shop.local/prodotto/maglietta-logo/?attribute_taglia=m",
        "description": "",
        "price": "19.90",
        "regular_price": "22.90",
        "stock_status": "outofstock",
        "stock_quantity": 0,
        "attributes": [{"id": 2, "name": "Taglia", "option": "M"}],
        "image": None,
        "global_unique_id": "",
    },
]


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeSession:
    """Simula requests.Session.request contro un'istanza WooCommerce nota."""

    def request(self, method, url, *, params=None, auth=None, timeout=None):
        assert method == "GET"
        params = params or {}
        if url.endswith("/products"):
            return _FakeResponse(PRODUCTS_PAGE_1 if params.get("page", 1) == 1 else [])
        if url.endswith("/products/102/variations"):
            return _FakeResponse(VARIATIONS_102 if params.get("page", 1) == 1 else [])
        raise AssertionError(f"URL non atteso nel fake: {url}")


def build_catalog():
    client = WooCommerceClient(
        "https://esempio-shop.local",
        "ck_fake",
        "cs_fake",
        session=_FakeSession(),
    )
    return fetch_catalog(
        "https://esempio-shop.local",
        "ck_fake",
        "cs_fake",
        seller_name="Esempio Shop SRL",
        currency="EUR",
        client=client,
    )


if __name__ == "__main__":
    cat = build_catalog()

    assert len(cat.products) == 2, f"attesi 2 prodotti, trovati {len(cat.products)}"

    tazza = next(p for p in cat.products if p.id == "TAZZA-001")
    assert tazza.brand == "CasaItalia"
    assert len(tazza.variants) == 1
    assert tazza.variants[0].price.amount == tazza.variants[0].price.amount  # sanity
    assert str(tazza.variants[0].price.amount) == "9.90"
    assert str(tazza.variants[0].list_price.amount) == "12.90"
    assert tazza.variants[0].barcodes[0].value == "8001234500019"

    maglietta = next(p for p in cat.products if p.id == "MAGLIETTA-LOGO")
    assert len(maglietta.variants) == 2
    taglia_m = next(v for v in maglietta.variants if v.id == "MAGLIETTA-LOGO-M")
    assert taglia_m.availability.available is False
    assert str(taglia_m.list_price.amount) == "22.90"
    assert taglia_m.options[0].value == "M"

    acp = catalog_to_acp(cat)
    errors = validate_acp_products(acp)
    print(json.dumps(acp, indent=2, ensure_ascii=False))
    print("\n--- VALIDAZIONE SCHEMA UFFICIALE ACP 2026-04-17 (via connettore WooCommerce) ---")
    if errors:
        print(f"FALLITA: {len(errors)} errori")
        for e in errors:
            print(" •", e)
        sys.exit(1)
    print("OK: catalogo WooCommerce -> canonico -> ACP conforme allo schema ufficiale.")
