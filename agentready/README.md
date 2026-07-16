# AgentReady

Repo: https://github.com/AlCap27/agentready

Toolkit open source (AGPL-3.0) per rendere i cataloghi delle PMI europee
visibili e comprensibili agli agenti AI (ACP, Google Merchant/UCP, MCP),
senza dipendere dall'auto-enrollment delle piattaforme proprietarie.

## Stato — v0.0.1 (core funzionante)

- `agentready/model.py` — Modello canonico prodotto (pydantic v2). Superset
  di ACP 2026-04-17 e Merchant Center. Prezzi in Decimal, conversione in
  minor units solo in export. Validazione unicità id.
- `agentready/exporters/acp.py` — Export canonico → ACP feed 2026-04-17.
  Rispetta `additionalProperties: false`; categorie propagate alle varianti.
- `agentready/validate.py` — Validazione contro `schemas/schema.feed.json`
  ufficiale (vendored dal repo agentic-commerce-protocol, Draft 2020-12).
- `agentready/connectors/woocommerce.py` — Connettore WooCommerce REST API v3
  → Catalog canonico. Prodotti "simple" e "variable" (+ varianti), categorie,
  media, barcode (`global_unique_id`), brand (estensione "WooCommerce
  Brands" o attributo pa_brand). Auth: Basic su HTTPS, OAuth 1.0a
  one-legged (RFC 5849) su HTTP — richiesto da WooCommerce stesso fuori SSL.
- `tests/test_smoke.py` — End-to-end: catalogo canonico → ACP → validazione
  schema ufficiale. **Passa.**
- `tests/test_woocommerce_mapping.py` — Mapping WooCommerce → canonico → ACP,
  offline (risposte REST simulate). **Passa.**
- `tests/test_woocommerce_smoke.py` — Stesso percorso contro un'istanza
  WooCommerce reale (env `WC_URL`/`WC_CONSUMER_KEY`/`WC_CONSUMER_SECRET`,
  skip se non impostate). **Passa** contro un'istanza locale via Docker
  (WordPress + WooCommerce, HTTP, auth OAuth1).
- `agentready/connectors/csv.py` — Connettore CSV generico → Catalog
  canonico. Wizard di column-mapping (`auto_detect_mapping`): tokenizza le
  intestazioni e le confronta con alias per campo (IT/EN) via similarità
  Jaccard, con warning leggibile per ogni campo non rilevato con sufficiente
  confidenza; il mapping risultante è una `dict[str, str]` salvabile/
  ricaricabile in JSON (`save_mapping`/`load_mapping`) per non ripetere il
  wizard ad ogni import. Raggruppa le righe in varianti dello stesso Product
  via una colonna `group_id` opzionale (stile Item Group ID).
- `tests/test_csv_smoke.py` — Wizard → mapping JSON → ingestion → ACP →
  validazione schema, offline. **Passa.**
- `agentready/exporters/merchant.py` — Export canonico → feed Google
  Merchant Center (TSV e XML/RSS con namespace `g:`), porta d'ingresso UCP.
  Granularità a livello di Variant (un item = un'offerta), come in ACP.
  Attenzione: la convenzione prezzi è invertita rispetto ad ACP — Merchant
  Center vuole `price` = prezzo pieno e `sale_price` = prezzo scontato,
  mentre nel modello canonico `price` è il prezzo corrente e `list_price`
  il prezzo pieno se in sconto (vedi `_price_fields` nel modulo).
- `tests/test_merchant_smoke.py` — Costruisce un catalogo, esporta in
  TSV/XML, riparsa entrambi (nessuno schema ufficiale vendorizzabile per
  Merchant Center, a differenza di ACP: la spec è documentazione prosa) e
  verifica i valori più delicati. **Passa.**
- `agentready/mcp_server.py` — Server MCP (FastMCP) auto-generato da un
  Catalog qualsiasi: `build_server(catalog)` espone `search_products`
  (testo libero + filtri categoria/brand/prezzo/disponibilità),
  `get_product` (dettaglio completo) e `check_availability` (stato di una
  variante/SKU). I tool ritornano JSON derivato da `model_dump(mode="json")`
  — nessuno schema duplicato a mano. `run_stdio(catalog)` per l'uso con
  client MCP desktop/IDE.
- `tests/test_mcp_server_smoke.py` — Round-trip protocollo MCP reale
  (`mcp.shared.memory.create_connected_server_and_client_session`:
  ClientSession vero collegato al server via stream in-memory, non solo
  unit test delle funzioni Python) — `initialize`, `list_tools`,
  `call_tool` sui tre tool, inclusi i casi di errore (id inesistente).
  **Passa.**
- `agentready/score.py` — Agent-Readiness Score + report data quality per
  merchant. Non valuta la conformità a un formato di export (già coperta da
  exporter/validate.py) ma la qualità intrinseca dei dati canonici: titolo,
  descrizione, brand, categorie, immagini, url, prezzo per variante,
  barcode, opzioni variante (per distinguere le varianti tra loro),
  quantità quando "in_stock". Ogni check ha un peso; `score_product`/
  `score_catalog` restituiscono un punteggio 0-100 con la lista dei problemi
  rilevati, `format_report` produce un report leggibile ordinato per
  problemi più diffusi e prodotti peggiori.
- `tests/test_score_smoke.py` — Un prodotto "da manuale" (score 100, zero
  issue) e uno scadente (quasi tutti i check falliscono) nello stesso
  catalogo: verifica discriminazione dei punteggi, summary aggregato e
  report leggibile. **Passa.**
- `agentready/agent_simulator.py` — Agent simulator: fa girare un vero
  agente Claude (tool use reale, non simulato) contro il server MCP per
  rispondere a query in linguaggio naturale sul catalogo. Per ogni query con
  un prodotto atteso non trovato, isola se è un problema di formulazione
  della ricerca da parte dell'agente (il motore MCP troverebbe il prodotto
  con la query letterale, l'agente ha cercato altro) o di qualità dati (il
  motore non lo trova nemmeno con la query letterale — incrocia con
  `agentready.score` per spiegare quali campi mancano). Richiede
  `AGENTREADY_API_KEY` (letta da un file `.env` nella root del progetto via
  python-dotenv) — chiama l'API Claude a pagamento, a differenza di tutto
  il resto del progetto. **Testato con chiamate reali** (claude-haiku-4-5):
  agente vero, tool use reale via protocollo MCP, entrambe le query di
  prova risolte correttamente.

```bash
pip install pydantic jsonschema requests mcp anthropic python-dotenv
python3 tests/test_smoke.py
python3 tests/test_woocommerce_mapping.py
python3 tests/test_csv_smoke.py
python3 tests/test_merchant_smoke.py
python3 tests/test_mcp_server_smoke.py
python3 tests/test_score_smoke.py
WC_URL=http://localhost:8089 WC_CONSUMER_KEY=ck_... WC_CONSUMER_SECRET=cs_... \
  python3 tests/test_woocommerce_smoke.py
```

Per l'agent simulator: creare un file `.env` nella root del progetto con
`AGENTREADY_API_KEY=sk-ant-...` (mai committarlo — è in `.gitignore`).

## Roadmap MVP (ordine di build)

1. ~~**Connettore WooCommerce** (REST API v3) → Catalog canonico.~~ **Fatto.**
2. ~~**Connettore CSV** riusando il pattern column-mapping wizard di PoliSim
   (auto-detect token-based, warning per campo, mapping salvabile JSON).~~
   **Fatto** (codice sorgente di PoliSim non disponibile in locale: pattern
   reimplementato da zero seguendo la descrizione — tokenizzazione +
   similarità Jaccard contro alias IT/EN, warning per campo, mapping JSON).
3. ~~**Exporter Google Merchant Center** (XML/TSV) — porta d'ingresso UCP.~~
   **Fatto.**
4. ~~**Server MCP auto-generato** (FastMCP): search_products, get_product,
   check_availability sul Catalog.~~ **Fatto.**
5. ~~**Agent-Readiness Score** + report data quality per merchant.~~ **Fatto.**
6. ~~**Agent simulator**: query reali via Claude API sul server MCP,
   report "perché il prodotto X non viene trovato".~~ **Fatto**, testato
   con chiamate reali (claude-haiku-4-5).
7. Fase 2 — **Plugin WordPress.org** (canale di distribuzione primario):
   wrapper PHP che chiama il motore Python o riimplementa l'export feed.

## Vincoli di progetto

- Il modello canonico è stabile; gli exporter sono adapter usa-e-getta
  (le spec ACP cambiano ogni ~6 settimane: aggiornare `schemas/` e adapter).
- Niente checkout/payment in fase 1.
- `Money.minor_units()` assume valute a 2 decimali — da estendere se
  servono JPY/KWD.
