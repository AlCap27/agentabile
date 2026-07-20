"""
Connettore: WooCommerce REST API v3 → Catalog canonico.

Legge i prodotti da un'istanza WooCommerce (`GET /wp-json/wc/v3/products`) e,
per i prodotti variabili, le relative varianti
(`GET /wp-json/wc/v3/products/{id}/variations`), mappandoli nel modello
canonico (agentabile.model.Catalog).

Autenticazione (vedi WooCommerce REST API docs, class-wc-rest-authentication.php):
- HTTPS: HTTP Basic Auth con consumer_key/consumer_secret (default).
- HTTP (istanza dev locale senza SSL): WooCommerce rifiuta Basic Auth e la
  semplice query string fuori da SSL — richiede OAuth 1.0a "one-legged"
  (RFC 5849, senza token, firma passata come parametro di query anziché
  header Authorization). Il client implementa questa firma automaticamente
  quando l'URL base non è https, così il connettore funziona sia in
  produzione (HTTPS) sia contro un'istanza WooCommerce locale in HTTP.

Copertura v1: prodotti "simple" e "variable" (grouped/external non ancora
supportati — vengono scartati, non generano errore).
"""
from __future__ import annotations

import hashlib
import hmac as hmac_lib
import re
import secrets
import time
from base64 import b64encode
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator, Optional
from urllib.parse import quote, urljoin

import requests

from agentabile.model import (
    Availability,
    AvailabilityStatus,
    Barcode,
    BarcodeType,
    Catalog,
    Category,
    Media,
    MediaType,
    Money,
    Product,
    Variant,
    VariantOption,
)

_DEFAULT_PER_PAGE = 100

_STOCK_STATUS_MAP = {
    "instock": AvailabilityStatus.in_stock,
    "outofstock": AvailabilityStatus.out_of_stock,
    "onbackorder": AvailabilityStatus.backorder,
}


class WooCommerceError(RuntimeError):
    """Errore di comunicazione o di risposta dall'API WooCommerce."""


def _rfc3986_quote(value: Any) -> str:
    """rawurlencode() PHP-compatibile: RFC 3986, '~' incluso tra i caratteri sicuri
    (comportamento nativo di urllib.parse.quote da Python 3.7)."""
    return quote(str(value), safe="")


def _oauth1_sign(method: str, url_no_query: str, params: dict[str, Any], consumer_secret: str) -> str:
    """Firma OAuth 1.0a "one-legged" secondo l'algoritmo esatto di
    WC_REST_Authentication::check_oauth_signature (vendored qui perché WooCommerce
    non espone questa logica come libreria riusabile)."""
    encoded_pairs = []
    for key in sorted(params.keys()):
        combined = f"{_rfc3986_quote(key)}={_rfc3986_quote(params[key])}"
        encoded_pairs.append(_rfc3986_quote(combined))
    query_string = "%26".join(encoded_pairs)
    string_to_sign = f"{method.upper()}&{_rfc3986_quote(url_no_query)}&{query_string}"
    digest = hmac_lib.new(
        f"{consumer_secret}&".encode(), string_to_sign.encode(), hashlib.sha256
    ).digest()
    return b64encode(digest).decode()


class WooCommerceClient:
    """Client HTTP minimale per WooCommerce REST API v3."""

    def __init__(
        self,
        base_url: str,
        consumer_key: str,
        consumer_secret: str,
        *,
        version: str = "wc/v3",
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        root = base_url.rstrip("/") + "/"
        self.api_root = urljoin(root, f"wp-json/{version}/")
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        # Fuori da HTTPS WooCommerce richiede OAuth 1.0a one-legged (vedi docstring modulo).
        self.use_oauth1 = not self.api_root.startswith("https://")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _request(self, method: str, path: str, *, params: Optional[dict[str, Any]] = None) -> Any:
        url = urljoin(self.api_root, path.lstrip("/"))
        params = dict(params or {})
        auth = None
        if self.use_oauth1:
            params.update(
                {
                    "oauth_consumer_key": self.consumer_key,
                    "oauth_nonce": secrets.token_hex(16),
                    "oauth_signature_method": "HMAC-SHA256",
                    "oauth_timestamp": str(int(time.time())),
                }
            )
            params["oauth_signature"] = _oauth1_sign(method, url, params, self.consumer_secret)
        else:
            auth = (self.consumer_key, self.consumer_secret)
        resp = self.session.request(method, url, params=params, auth=auth, timeout=self.timeout)
        if resp.status_code >= 400:
            raise WooCommerceError(f"{method} {url} -> HTTP {resp.status_code}: {resp.text[:500]}")
        return resp.json()

    def get_products(
        self, *, per_page: int = _DEFAULT_PER_PAGE, status: str = "publish"
    ) -> Iterator[dict[str, Any]]:
        """Itera tutti i prodotti paginando l'endpoint /products."""
        page = 1
        while True:
            batch = self._request(
                "GET", "products", params={"per_page": per_page, "page": page, "status": status}
            )
            if not batch:
                return
            yield from batch
            if len(batch) < per_page:
                return
            page += 1

    def get_variations(
        self, product_id: int, *, per_page: int = _DEFAULT_PER_PAGE
    ) -> Iterator[dict[str, Any]]:
        """Itera tutte le varianti di un prodotto variabile."""
        page = 1
        while True:
            batch = self._request(
                "GET",
                f"products/{product_id}/variations",
                params={"per_page": per_page, "page": page},
            )
            if not batch:
                return
            yield from batch
            if len(batch) < per_page:
                return
            page += 1


def _strip_html(html: str) -> Optional[str]:
    text = re.sub(r"<[^>]+>", " ", html or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _money(raw_value: Any, currency: str) -> Optional[Money]:
    if raw_value in (None, ""):
        return None
    try:
        amount = Decimal(str(raw_value))
    except InvalidOperation:
        return None
    if amount < 0:
        return None
    return Money(amount=amount, currency=currency)


def _list_price(price: Optional[Money], regular: Optional[Money]) -> Optional[Money]:
    """list_price ha senso solo se il prezzo pieno è effettivamente più alto
    del prezzo corrente (prodotto in sconto)."""
    if price and regular and regular.amount > price.amount:
        return regular
    return None


def _availability(raw: dict[str, Any]) -> Availability:
    status = _STOCK_STATUS_MAP.get(raw.get("stock_status"), AvailabilityStatus.in_stock)
    return Availability(
        available=status in (AvailabilityStatus.in_stock, AvailabilityStatus.backorder),
        status=status,
        quantity=raw.get("stock_quantity"),
    )


def _barcodes(raw: dict[str, Any]) -> list[Barcode]:
    # Campo nativo `global_unique_id` (GTIN/UPC/EAN/ISBN) presente da WC 8.9+.
    gid = (raw.get("global_unique_id") or "").strip()
    if not gid:
        return []
    return [Barcode(type=BarcodeType.gtin, value=gid)]


def _media_from_images(images: list[dict[str, Any]]) -> list[Media]:
    out: list[Media] = []
    for img in images:
        src = img.get("src")
        if not src:
            continue
        out.append(Media(type=MediaType.image, url=src, alt_text=img.get("alt") or None))
    return out


def _categories(raw_categories: list[dict[str, Any]]) -> list[Category]:
    return [Category(value=c["name"], taxonomy="woocommerce") for c in raw_categories if c.get("name")]


def _brand(raw: dict[str, Any]) -> Optional[str]:
    # Estensione ufficiale "WooCommerce Brands" espone `brands` come le `categories`.
    brands = raw.get("brands") or []
    if brands and brands[0].get("name"):
        return brands[0]["name"]
    # Fallback: attributo prodotto chiamato Brand/Marca/pa_brand.
    for attr in raw.get("attributes") or []:
        name = (attr.get("name") or "").strip().lower()
        if name in ("brand", "marca", "pa_brand"):
            options = attr.get("options") or []
            if options:
                return str(options[0])
    return None


def _attributes_to_dict(raw_attrs: list[dict[str, Any]]) -> dict[str, str]:
    """Attributi prodotto non usati per generare varianti → attributi liberi canonici."""
    out: dict[str, str] = {}
    for attr in raw_attrs:
        name = attr.get("name")
        options = attr.get("options") or []
        if name and options:
            out[name] = ", ".join(str(o) for o in options)
    return out


def _woo_id(raw: dict[str, Any]) -> str:
    sku = (raw.get("sku") or "").strip()
    return sku or f"woo-{raw['id']}"


def _simple_variant(raw: dict[str, Any], currency: str) -> Variant:
    price = _money(raw.get("price"), currency)
    regular = _money(raw.get("regular_price"), currency)
    variant_id = _woo_id(raw)
    return Variant(
        id=variant_id,
        title=raw.get("name") or variant_id,
        description_plain=_strip_html(raw.get("short_description") or ""),
        url=raw.get("permalink") or None,
        barcodes=_barcodes(raw),
        price=price,
        list_price=_list_price(price, regular),
        availability=_availability(raw),
        media=_media_from_images(raw.get("images") or []),
        attributes=_attributes_to_dict(raw.get("attributes") or []),
    )


def _variation_variant(raw: dict[str, Any], parent: dict[str, Any], currency: str) -> Variant:
    price = _money(raw.get("price"), currency)
    regular = _money(raw.get("regular_price"), currency)
    variant_id = _woo_id(raw)
    options = [
        VariantOption(name=a.get("name", ""), value=a.get("option", ""))
        for a in raw.get("attributes") or []
        if a.get("option")
    ]
    title_bits = [o.value for o in options if o.value]
    parent_name = parent.get("name") or variant_id
    title = f"{parent_name} — {', '.join(title_bits)}" if title_bits else parent_name
    image = raw.get("image")
    return Variant(
        id=variant_id,
        title=title,
        description_plain=_strip_html(raw.get("description") or ""),
        url=raw.get("permalink") or None,
        barcodes=_barcodes(raw),
        price=price,
        list_price=_list_price(price, regular),
        availability=_availability(raw),
        options=options,
        media=_media_from_images([image] if image else []),
    )


def woo_product_to_product(
    raw: dict[str, Any], client: WooCommerceClient, currency: str
) -> Optional[Product]:
    """Converte un prodotto WooCommerce (+ eventuali varianti) in Product canonico.

    Ritorna None per i tipi non ancora supportati (grouped, external) o per
    prodotti variabili senza nessuna variante pubblicata.
    """
    wtype = raw.get("type")
    if wtype not in ("simple", "variable"):
        return None

    if wtype == "variable":
        variants = [_variation_variant(v, raw, currency) for v in client.get_variations(raw["id"])]
        if not variants:
            return None
    else:
        variants = [_simple_variant(raw, currency)]

    return Product(
        id=_woo_id(raw),
        title=raw.get("name") or _woo_id(raw),
        brand=_brand(raw),
        description_plain=_strip_html(raw.get("short_description") or ""),
        description_html=raw.get("description") or None,
        url=raw.get("permalink") or None,
        categories=_categories(raw.get("categories") or []),
        media=_media_from_images(raw.get("images") or []),
        variants=variants,
    )


def fetch_catalog(
    base_url: str,
    consumer_key: str,
    consumer_secret: str,
    *,
    seller_name: str,
    currency: str = "EUR",
    status: str = "publish",
    client: Optional[WooCommerceClient] = None,
) -> Catalog:
    """Scarica l'intero catalogo da un'istanza WooCommerce e lo normalizza
    in un Catalog canonico, pronto per gli exporter (ACP, ...)."""
    wc = client or WooCommerceClient(base_url, consumer_key, consumer_secret)
    products: list[Product] = []
    for raw in wc.get_products(status=status):
        product = woo_product_to_product(raw, wc, currency)
        if product is not None:
            products.append(product)
    return Catalog(seller_name=seller_name, seller_url=base_url, products=products)
