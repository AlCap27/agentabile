"""
Server MCP (FastMCP) auto-generato dal Catalog canonico.

"Auto-generato" nel senso che `build_server(catalog)` genera un server MCP
completo per un Catalog qualsiasi — nessun codice specifico per merchant.
Tre tool, pensati per un agente che deve rispondere a domande sul catalogo:

- `search_products` — ricerca testuale (match parziale per token su titolo,
  brand, descrizione, categorie, titoli variante) + filtri strutturati
  (categoria, brand, prezzo, disponibilità).
- `get_product` — dettaglio completo di un prodotto (tutte le varianti).
- `check_availability` — stato di disponibilità di una specifica variante/SKU.

I tool ritornano dict JSON-serializzabili ricavati da
`model.model_dump(mode="json")`: nessuno schema MCP duplicato a mano, il
modello canonico resta l'unica fonte di verità (vedi vincoli di progetto
nel README).
"""
from __future__ import annotations

import re
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from agentready.model import Catalog, Product, Variant


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower()) if t]


def _searchable_text(product: Product) -> str:
    parts = [product.title, product.brand or "", product.description_plain or ""]
    parts += [c.value for c in product.categories]
    parts += [v.title for v in product.variants]
    return " ".join(parts)


def _match_score(query_tokens: list[str], haystack_tokens: set[str]) -> float:
    """Frazione di token della query trovati (per sottostringa) nell'haystack.
    Nessuna query -> match universale (score 1), usato per liste filtrate senza testo."""
    if not query_tokens:
        return 1.0
    hits = sum(1 for t in query_tokens if any(t in h for h in haystack_tokens))
    return hits / len(query_tokens)


def _product_summary(product: Product) -> dict[str, Any]:
    prices = [v.price.amount for v in product.variants if v.price]
    priced_variant = next((v for v in product.variants if v.price), None)
    return {
        "id": product.id,
        "title": product.title,
        "brand": product.brand,
        "url": str(product.url) if product.url else None,
        "categories": [c.value for c in product.categories],
        "image_url": str(product.media[0].url) if product.media else None,
        "price_min": str(min(prices)) if prices else None,
        "price_max": str(max(prices)) if prices else None,
        "currency": priced_variant.price.currency if priced_variant else None,
        "any_in_stock": any(v.availability.available for v in product.variants),
        "variant_count": len(product.variants),
    }


def _find_product(catalog: Catalog, product_id: str) -> Product:
    for p in catalog.products:
        if p.id == product_id:
            return p
    raise ValueError(f"Prodotto non trovato: {product_id}")


def _find_variant(catalog: Catalog, variant_id: str) -> tuple[Product, Variant]:
    for p in catalog.products:
        for v in p.variants:
            if v.id == variant_id:
                return p, v
    raise ValueError(f"Variante non trovata: {variant_id}")


def build_server(catalog: Catalog, *, name: str = "AgentReady Catalog") -> FastMCP:
    """Genera un server FastMCP con i tool di ricerca/lettura sul Catalog dato."""
    mcp = FastMCP(
        name,
        instructions=(
            f"Catalogo prodotti di {catalog.seller_name}. Usa search_products per "
            "trovare prodotti, get_product per il dettaglio completo, "
            "check_availability per lo stato di una specifica variante/SKU."
        ),
    )

    @mcp.tool()
    def search_products(
        query: Optional[str] = None,
        category: Optional[str] = None,
        brand: Optional[str] = None,
        in_stock_only: bool = False,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Cerca prodotti nel catalogo per testo libero ed eventuali filtri.

        `query` cerca su titolo, brand, descrizione, categorie e titoli
        variante (match parziale per token, non case-sensitive).
        `min_price`/`max_price` confrontano l'importo numerico di qualunque
        variante del prodotto: nessuna conversione valutaria, assume la
        valuta di default del catalogo.
        """
        query_tokens = _tokenize(query) if query else []
        scored: list[tuple[float, Product]] = []
        for product in catalog.products:
            if category and not any(category.lower() in c.value.lower() for c in product.categories):
                continue
            if brand and (not product.brand or brand.lower() not in product.brand.lower()):
                continue
            if in_stock_only and not any(v.availability.available for v in product.variants):
                continue
            if min_price is not None or max_price is not None:
                prices = [v.price.amount for v in product.variants if v.price]
                if not prices:
                    continue
                if min_price is not None and max(prices) < min_price:
                    continue
                if max_price is not None and min(prices) > max_price:
                    continue
            haystack = set(_tokenize(_searchable_text(product)))
            score = _match_score(query_tokens, haystack)
            if score <= 0:
                continue
            scored.append((score, product))

        scored.sort(key=lambda sp: sp[0], reverse=True)
        return [_product_summary(p) for _score, p in scored[:limit]]

    @mcp.tool()
    def get_product(product_id: str) -> dict[str, Any]:
        """Dettaglio completo di un prodotto (tutte le varianti, media,
        categorie), identificato dal suo id canonico."""
        product = _find_product(catalog, product_id)
        return product.model_dump(mode="json")

    @mcp.tool()
    def check_availability(variant_id: str) -> dict[str, Any]:
        """Stato di disponibilità di una specifica variante/SKU."""
        product, variant = _find_variant(catalog, variant_id)
        return {
            "product_id": product.id,
            "product_title": product.title,
            "variant_id": variant.id,
            "variant_title": variant.title,
            "available": variant.availability.available,
            "status": variant.availability.status.value,
            "quantity": variant.availability.quantity,
        }

    return mcp


def run_stdio(catalog: Catalog, *, name: str = "AgentReady Catalog") -> None:
    """Entry point: avvia il server MCP su stdio (uso tipico con client
    desktop/IDE che lanciano il processo direttamente)."""
    build_server(catalog, name=name).run(transport="stdio")
