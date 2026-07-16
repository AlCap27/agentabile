"""
Agent simulator: query reali via Claude API sul server MCP di AgentReady.

A differenza di `tests/test_mcp_server_smoke.py` (che chiama i tool
direttamente via protocollo MCP), questo modulo fa girare un vero agente
Claude — con tool use reale, non simulato — che usa i tool del server MCP
(`search_products`, `get_product`, `check_availability`) per rispondere a
domande in linguaggio naturale su un catalogo. Per ogni query con un
prodotto atteso non trovato, produce un report diagnostico "perché il
prodotto X non viene trovato":

1. Confronta cosa l'agente ha effettivamente cercato con cosa avrebbe
   trovato una ricerca letterale sulla query dell'utente (isola: problema
   di formulazione della ricerca da parte dell'agente vs problema di dati).
2. Se anche la ricerca letterale fallisce, incrocia con l'Agent-Readiness
   Score (`agentready.score`) del prodotto per spiegare quali campi
   mancanti probabilmente causano il mancato match.

Richiede una API key Anthropic valida in `AGENTREADY_API_KEY` (letta da un
file `.env` nella root del progetto via python-dotenv, o già presente
nell'ambiente) — le chiamate a run_simulation() hanno un costo reale
sull'account Anthropic dell'utente, a differenza degli altri moduli del
progetto che sono gratuiti/locali.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from agentready.mcp_server import build_server
from agentready.model import Catalog
from agentready.score import score_product

DEFAULT_MODEL = "claude-opus-4-8"

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

_SYSTEM_PROMPT = (
    "Sei un agente shopping che aiuta un utente a trovare prodotti nel catalogo di "
    "{seller_name}. Usa i tool disponibili (search_products, get_product, "
    "check_availability) per rispondere alle domande dell'utente. Se non trovi un "
    "prodotto pertinente nel catalogo, dillo chiaramente invece di inventare risultati "
    "o di rispondere dalla tua conoscenza generale."
)


@dataclass
class SimulatedQuery:
    query: str
    expected_product_id: Optional[str] = None


@dataclass
class QueryResult:
    query: str
    final_text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    expected_product_id: Optional[str] = None
    found: Optional[bool] = None  # None se non c'era un prodotto atteso da verificare
    diagnosis: Optional[str] = None


def _mentions_product(text: str, catalog: Catalog, product_id: str) -> bool:
    text_low = text.lower()
    if product_id.lower() in text_low:
        return True
    product = next((p for p in catalog.products if p.id == product_id), None)
    return bool(product and product.title.lower() in text_low)


async def _diagnose_miss(session, catalog: Catalog, query: SimulatedQuery) -> str:
    """Isola se il mancato ritrovamento è un problema di ricerca dell'agente
    o di qualità dei dati del prodotto, incrociando con l'Agent-Readiness Score."""
    lines: list[str] = []
    res = await session.call_tool("search_products", {"query": query.query})
    ground_truth_ids: set[str] = set()
    if not res.isError and res.structuredContent:
        ground_truth_ids = {p["id"] for p in res.structuredContent.get("result", [])}

    if query.expected_product_id in ground_truth_ids:
        lines.append(
            f"Il motore di ricerca del server MCP TROVEREBBE '{query.expected_product_id}' "
            f"per la query letterale \"{query.query}\", ma l'agente non l'ha recuperato o "
            "menzionato nella risposta finale: probabile problema di formulazione della "
            "ricerca da parte dell'agente (query troppo diversa da quella usata), non di dati."
        )
    else:
        lines.append(
            f"Il motore di ricerca del server MCP NON trova '{query.expected_product_id}' "
            f"nemmeno con la query letterale \"{query.query}\": è un problema di dati/qualità "
            "del prodotto, non dell'agente."
        )
        product = next((p for p in catalog.products if p.id == query.expected_product_id), None)
        if product is None:
            lines.append("Prodotto non presente nel catalogo fornito alla simulazione.")
        else:
            ps = score_product(product)
            if ps.issues:
                lines.append(f"Agent-Readiness Score del prodotto: {ps.score}/100. Problemi rilevati:")
                for issue in ps.issues:
                    lines.append(f"  - ({issue.severity}) {issue.field}: {issue.message}")
            else:
                lines.append(
                    "Nessun problema rilevato dall'Agent-Readiness Score: la query dell'utente "
                    "probabilmente non condivide alcun termine con titolo/categoria/descrizione "
                    "del prodotto (mismatch semantico tra il linguaggio dell'utente e quello del catalogo)."
                )
    return "\n".join(lines)


async def _simulate_one(
    client, session, tools, catalog: Catalog, query: SimulatedQuery, *, model: str, max_iterations: int
) -> QueryResult:
    runner = client.beta.messages.tool_runner(
        model=model,
        max_tokens=2048,
        system=_SYSTEM_PROMPT.format(seller_name=catalog.seller_name),
        tools=tools,
        messages=[{"role": "user", "content": query.query}],
        max_iterations=max_iterations,
    )

    tool_calls: list[dict[str, Any]] = []
    final_text = ""
    async for message in runner:
        for block in message.content:
            if block.type == "tool_use":
                tool_calls.append({"name": block.name, "input": block.input})
            elif block.type == "text":
                final_text = block.text

    found: Optional[bool] = None
    diagnosis: Optional[str] = None
    if query.expected_product_id:
        found = _mentions_product(final_text, catalog, query.expected_product_id)
        if not found:
            diagnosis = await _diagnose_miss(session, catalog, query)

    return QueryResult(
        query=query.query,
        final_text=final_text,
        tool_calls=tool_calls,
        expected_product_id=query.expected_product_id,
        found=found,
        diagnosis=diagnosis,
    )


def _build_client():
    from anthropic import AsyncAnthropic

    api_key = os.environ.get("AGENTREADY_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Variabile d'ambiente AGENTREADY_API_KEY mancante. Impostala nel file .env "
            f"nella root del progetto ({_PROJECT_ROOT / '.env'}) o nell'ambiente prima di "
            "chiamare run_simulation() — questo modulo esegue chiamate reali all'API Claude "
            "con un costo a consumo sull'account Anthropic."
        )
    return AsyncAnthropic(api_key=api_key)


async def _run_all(
    catalog: Catalog, queries: list[SimulatedQuery], *, model: str, max_iterations: int
) -> list[QueryResult]:
    from anthropic.lib.tools.mcp import async_mcp_tool
    from mcp.shared.memory import create_connected_server_and_client_session

    server = build_server(catalog)
    client = _build_client()
    results: list[QueryResult] = []
    async with create_connected_server_and_client_session(server) as session:
        tools_result = await session.list_tools()
        tools = [async_mcp_tool(t, session) for t in tools_result.tools]
        for q in queries:
            results.append(
                await _simulate_one(client, session, tools, catalog, q, model=model, max_iterations=max_iterations)
            )
    return results


def run_simulation(
    catalog: Catalog,
    queries: list[SimulatedQuery],
    *,
    model: str = DEFAULT_MODEL,
    max_iterations: int = 6,
) -> list[QueryResult]:
    """Esegue le query contro il server MCP tramite un vero agente Claude
    (tool use reale). Richiede una API key Anthropic valida: ogni chiamata
    ha un costo reale sull'account dell'utente."""
    return asyncio.run(_run_all(catalog, queries, model=model, max_iterations=max_iterations))


def format_report(results: list[QueryResult]) -> str:
    lines = ["Agent Simulator — report query"]
    misses = [r for r in results if r.expected_product_id and r.found is False]
    hits = [r for r in results if r.expected_product_id and r.found is True]
    lines.append(f"Query totali: {len(results)} | trovati: {len(hits)} | mancati: {len(misses)}")
    lines.append("")
    for r in results:
        lines.append(f'Query: "{r.query}"')
        if r.tool_calls:
            calls = ", ".join(f"{c['name']}({c['input']})" for c in r.tool_calls)
            lines.append(f"  Tool chiamati: {calls}")
        else:
            lines.append("  Tool chiamati: nessuno")
        lines.append(f"  Risposta: {r.final_text[:200]}")
        if r.expected_product_id:
            esito = "TROVATO" if r.found else "NON TROVATO"
            lines.append(f"  Prodotto atteso '{r.expected_product_id}': {esito}")
            if r.diagnosis:
                for dl in r.diagnosis.splitlines():
                    lines.append(f"    {dl}")
        lines.append("")
    return "\n".join(lines)
