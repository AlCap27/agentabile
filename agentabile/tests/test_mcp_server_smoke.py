"""Smoke test del server MCP: round-trip protocollo reale (non solo unit
test delle funzioni Python) via `mcp.shared.memory.
create_connected_server_and_client_session`, che collega un vero
ClientSession a un vero FastMCP server su stream in-memory — nessun
sottoprocesso stdio necessario, ma il protocollo attraversato è quello
reale (initialize, list_tools, call_tool).
"""
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.shared.memory import create_connected_server_and_client_session

from agentabile.model import (
    Availability, AvailabilityStatus, Catalog, Category, Media, Money,
    Product, Variant,
)
from agentabile.mcp_server import build_server


def build_catalog() -> Catalog:
    moka = Product(
        id="MOKA-CLASSIC",
        title="Caffettiera Moka Classica",
        brand="CasaItalia",
        description_plain="Caffettiera moka in alluminio, made in Italy.",
        categories=[Category(value="Casa > Cucina > Caffettiere", taxonomy="merchant")],
        media=[Media(url="https://example-shop.it/img/moka.jpg")],
        variants=[
            Variant(
                id="MOKA-3TZ", title="Moka Classica — 3 tazze",
                price=Money(amount=Decimal("19.90"), currency="EUR"),
            ),
            Variant(
                id="MOKA-6TZ", title="Moka Classica — 6 tazze",
                price=Money(amount=Decimal("27.50"), currency="EUR"),
                availability=Availability(available=False, status=AvailabilityStatus.out_of_stock),
            ),
        ],
    )
    maglietta = Product(
        id="MAGLIETTA-LOGO",
        title="Maglietta Logo",
        brand="StreetWear Co",
        categories=[Category(value="Abbigliamento > T-shirt", taxonomy="merchant")],
        variants=[
            Variant(
                id="MAGLIETTA-LOGO-M", title="Maglietta Logo — M",
                price=Money(amount=Decimal("19.90"), currency="EUR"),
            ),
        ],
    )
    return Catalog(seller_name="Example Shop SRL", products=[moka, maglietta])


async def main() -> None:
    catalog = build_catalog()
    server = build_server(catalog, name="Example Shop Catalog")

    async with create_connected_server_and_client_session(server) as session:
        tools = (await session.list_tools()).tools
        tool_names = {t.name for t in tools}
        assert tool_names == {"search_products", "get_product", "check_availability"}, tool_names

        # search_products: query testuale
        res = await session.call_tool("search_products", {"query": "moka"})
        assert not res.isError, res.content
        hits = res.structuredContent["result"]
        assert len(hits) == 1 and hits[0]["id"] == "MOKA-CLASSIC", hits

        # search_products: nessuna query, solo filtro categoria
        res = await session.call_tool("search_products", {"category": "abbigliamento"})
        assert not res.isError
        hits = res.structuredContent["result"]
        assert [h["id"] for h in hits] == ["MAGLIETTA-LOGO"]

        # search_products: filtro prezzo che esclude tutto
        res = await session.call_tool("search_products", {"min_price": 100})
        assert not res.isError
        assert res.structuredContent["result"] == []

        # search_products: in_stock_only true -> entrambi hanno almeno una variante disponibile
        res = await session.call_tool("search_products", {"in_stock_only": True})
        assert not res.isError
        assert {h["id"] for h in res.structuredContent["result"]} == {"MOKA-CLASSIC", "MAGLIETTA-LOGO"}

        # get_product: dettaglio completo
        res = await session.call_tool("get_product", {"product_id": "MOKA-CLASSIC"})
        assert not res.isError
        product = res.structuredContent
        assert len(product["variants"]) == 2
        assert product["variants"][0]["price"]["amount"] == "19.90"

        # get_product: id inesistente -> errore di tool, non crash del server
        res = await session.call_tool("get_product", {"product_id": "NON-ESISTE"})
        assert res.isError
        assert "non trovato" in res.content[0].text.lower()

        # check_availability: variante disponibile e non disponibile
        res = await session.call_tool("check_availability", {"variant_id": "MOKA-3TZ"})
        assert not res.isError
        assert res.structuredContent["available"] is True
        assert res.structuredContent["status"] == "in_stock"

        res = await session.call_tool("check_availability", {"variant_id": "MOKA-6TZ"})
        assert not res.isError
        assert res.structuredContent["available"] is False
        assert res.structuredContent["status"] == "out_of_stock"

        res = await session.call_tool("check_availability", {"variant_id": "NON-ESISTE"})
        assert res.isError

    print("OK: server MCP (search_products, get_product, check_availability) verificato via protocollo reale.")


if __name__ == "__main__":
    asyncio.run(main())
