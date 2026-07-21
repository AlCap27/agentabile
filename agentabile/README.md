# Agentabile

Repo: https://github.com/AlCap27/agentabile

Toolkit open source (AGPL-3.0) per rendere i cataloghi delle PMI europee
visibili e comprensibili agli agenti AI (ACP, Google Merchant/UCP, MCP),
senza dipendere dall'auto-enrollment delle piattaforme proprietarie.

## Stato — v0.0.1 (core funzionante)

- `agentabile/model.py` — Modello canonico prodotto (pydantic v2). Superset
  di ACP 2026-04-17 e Merchant Center. Prezzi in Decimal, conversione in
  minor units solo in export. Validazione unicità id.
- `agentabile/exporters/acp.py` — Export canonico → ACP feed 2026-04-17.
  Rispetta `additionalProperties: false`; categorie propagate alle varianti.
- `agentabile/validate.py` — Validazione contro `schemas/schema.feed.json`
  ufficiale (vendored dal repo agentic-commerce-protocol, Draft 2020-12).
- `agentabile/connectors/woocommerce.py` — Connettore WooCommerce REST API v3
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
- `agentabile/connectors/csv.py` — Connettore CSV generico → Catalog
  canonico. Wizard di column-mapping (`auto_detect_mapping`): tokenizza le
  intestazioni e le confronta con alias per campo (IT/EN) via similarità
  Jaccard, con warning leggibile per ogni campo non rilevato con sufficiente
  confidenza; il mapping risultante è una `dict[str, str]` salvabile/
  ricaricabile in JSON (`save_mapping`/`load_mapping`) per non ripetere il
  wizard ad ogni import. Raggruppa le righe in varianti dello stesso Product
  via una colonna `group_id` opzionale (stile Item Group ID).
- `tests/test_csv_smoke.py` — Wizard → mapping JSON → ingestion → ACP →
  validazione schema, offline. **Passa.**
- `agentabile/exporters/merchant.py` — Export canonico → feed Google
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
- `agentabile/mcp_server.py` — Server MCP (FastMCP) auto-generato da un
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
- `agentabile/score.py` — Agent-Readiness Score + report data quality per
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
- `agentabile/agent_simulator.py` — Agent simulator: fa girare un vero
  agente Claude (tool use reale, non simulato) contro il server MCP per
  rispondere a query in linguaggio naturale sul catalogo. Per ogni query con
  un prodotto atteso non trovato, isola se è un problema di formulazione
  della ricerca da parte dell'agente (il motore MCP troverebbe il prodotto
  con la query letterale, l'agente ha cercato altro) o di qualità dati (il
  motore non lo trova nemmeno con la query letterale — incrocia con
  `agentabile.score` per spiegare quali campi mancano). Richiede
  `AGENTABILE_API_KEY` (letta da un file `.env` nella root del progetto via
  python-dotenv) — chiama l'API Claude a pagamento, a differenza di tutto
  il resto del progetto. **Testato con chiamate reali** (claude-haiku-4-5):
  agente vero, tool use reale via protocollo MCP, entrambe le query di
  prova risolte correttamente.

```bash
pip install pydantic jsonschema requests mcp anthropic python-dotenv
pip install httpx selectolax extruct protego  # solo per agentabile.evaluator (scan gratuito)
python3 tests/test_smoke.py
python3 tests/test_woocommerce_mapping.py
python3 tests/test_csv_smoke.py
python3 tests/test_merchant_smoke.py
python3 tests/test_mcp_server_smoke.py
python3 tests/test_score_smoke.py
python3 tests/test_evaluator_smoke.py
WC_URL=http://localhost:8089 WC_CONSUMER_KEY=ck_... WC_CONSUMER_SECRET=cs_... \
  python3 tests/test_woocommerce_smoke.py
```

## Evaluator — scan gratuito (`agentabile/evaluator/`)

Fase 2 (implementazione) di `EVALUATOR_DESIGN.md` (design approvato da Alex
il 2026-07-21). Due evidence provider su un unico scoring engine, l'engine
non sa mai da dove viene l'evidenza:

- `evidence.py` — contratto dati (`Evidence`, `RubricItem`, `AxisScore`,
  `ScanReport`, pydantic v2).
- `engine.py` — scoring generico rubrica+evidenze -> punteggio per asse
  (`score(asse) = round(100 * Σpeso(PASS) / Σpeso(PASS∪FAIL))`; denominatore
  0 -> asse `N/A`, mai zero).
- `rubric_ar.py` — rubrica AR-* costruita da `schemas/agentready.spec.json`
  (mai trascritta a mano), chiavata per `stableId`: un requisito nuovo in
  un MINOR bump della spec produce un warning esplicito invece di rompere.
  Include l'item sintetico `AR-COMM-ANY` (i requisiti Commerce della spec
  sono alternativi, sommarli sarebbe scorretto).
- `providers/catalog.py` — adapter Catalog canonico -> Evidence per la
  rubrica DQ-* (data quality): `agentabile.score` ora delega qui + a
  `engine.py`, con output numerico verificato identico a prima del
  refactoring (`tests/test_score_smoke.py`, invariato, passa).
- `providers/site/` — SiteProvider (scan gratuito da URL):
  `fetcher.py` (robots.txt via protego, rate limit 1 req/s o Crawl-delay
  se maggiore, budget pagine/probe/banda/tempo, canary anti-soft-404,
  user-agent `AgentabileBot/1.0`), `context.py` (stato di uno scan),
  `checks.py` (un check per requisito AR-* verificabile con fetch
  statico — mappa 1:1 con EVALUATOR_DESIGN.md §3), `scan.py`
  (orchestratore: homepage -> sitemap -> selezione pagine -> estrazione
  JSON-LD/microdata via extruct -> gate commerce -> check -> `ScanReport`).

Decisione di design non riaperta in Fase 2: il gate commerce agisce
sull'intero asse Transactability, non solo su `AR-COMM-ANY` — su un sito
senza superficie e-commerce l'asse T è **sempre** `N/A` (mai uno zero
fuorviante calcolato dal solo `AR-IDEN-01`).

**Scostamento numerico dal design, segnalato ad Alex**: `EVALUATOR_DESIGN.md`
§5 stima "~15 probe leggere" (tilde = stima, a differenza degli altri
numeri della stessa frase che sono hard cap espliciti). La mappa completa
dei check AR-* richiede ~20-22 percorsi well-known distinti solo per
Capabilities+Identity+Commerce: con 15 lo scan esauriva il budget di probe
prima di arrivare ai check Commerce (proprio quelli critici per l'asse
Transactability). Alzato a 25 in `fetcher.py` (`MAX_PROBES`), restando ben
dentro l'hard cap esplicito di 45 richieste totali (uno scan reale usa
tipicamente 2-9 pagine, non 25).

**Verificato con evidenza reale** (`tests/test_evaluator_live.py`, da
lanciare a mano — richiede rete, ~1-2 minuti per il rate limit):
- Sito e-commerce reale (istanza WooCommerce Docker locale +
  plugin Agentabile installato, vedi memoria `woocommerce-local-docker`):
  gate commerce aperto, Transactability numerico, `AR-COMM-02`/
  `AR-COMM-ANY` **PASS reale** via il feed ACP del plugin.
- Sito editoriale reale (`www.agentready.org`): Visibility numerico,
  Transactability `N/A`.
- Sito senza segnali AR-* (`example.com`): Transactability `N/A` (mai 0).
- Rifiuto per `robots.txt: Disallow: /` verificato in
  `tests/test_evaluator_smoke.py` (server locale, scenario 3): scan
  fermato, nessun punteggio inventato — non si è cercato un sito pubblico
  che neghi la scansione solo per testarlo.
- Bug reale trovato e corretto durante la verifica: un errore di rete
  transitorio sul fetch di robots.txt veniva trattato silenziosamente
  come "robots.txt assente" (permissivo + `AR-DISC-01` FAIL). Ora
  distinto esplicitamente come `UNVERIFIABLE` (`Fetcher.robots_fetch_error`),
  con nota in `ScanReport.limits`.

**Limiti noti** (emersi implementando, non decisioni da riaprire ma da
tenere presenti leggendo un report):
- **L'applicabilità condizionale (N/A vs FAIL) è un'euristica hard-coded
  in `checks.py`, non derivata dallo spec a runtime.** Il campo `applies`
  di `agentready.spec.json` (es. "Products that expose an HTTP API") è
  testo libero pensato per un lettore umano — `rubric_ar.py` non lo legge
  mai (`build_rubric()` usa solo `stableId`, `name`, `strength`). La
  decisione concreta "questo sito espone un'API quindi CAPA-08 è
  applicabile" è scritta a mano in ogni `check_*` come proxy statico
  dell'intento della spec (es. `_openapi_doc()` prova solo
  `/openapi.json` e `/swagger.json`): un sito con un'API reale ma senza
  uno di quei due file well-known verrebbe classificato `N/A` invece di
  `FAIL`.
- **5 degli 11 check Capability/Identity implementati in v1 non possono
  strutturalmente restituire FAIL** — non è assenza di casi di test, è
  assenza del branch `Outcome.FAIL` nel codice: `AR-CAPA-01`,
  `AR-CAPA-04`, `AR-CAPA-08`, `AR-CAPA-09`, `AR-IDEN-03`. Per questi
  l'unico binario osservabile è PASS/N/A: "requisito applicabile ma non
  soddisfatto" e "superficie non rilevata" collassano nello stesso esito
  N/A, perché in v1 non c'è un fetch statico affidabile per distinguerli.
  Gli altri 6 check (`AR-CAPA-02`, `AR-IDEN-01`, `AR-IDEN-02`,
  `AR-IDEN-04`, `AR-IDEN-05`, `AR-IDEN-06`) hanno davvero tre esiti
  possibili, quasi sempre ancorati a un segnale correlato più debole
  (es. `AR-IDEN-06` usa `_openapi_doc()`: se un'API è rilevata ma manca
  `api-catalog`, è FAIL; se non c'è alcun segnale di API, è N/A).

**Non ancora fatto** (Fase 2 prosegue in una sessione successiva): punto 4
dell'ordine di implementazione (frontend minimo) — il design chiede
esplicitamente di riusare pattern PoliSim se applicabili, ma il codice
sorgente di PoliSim non è disponibile in locale (vedi memoria
`agentready-project`): da chiarire con Alex prima di costruire un
frontend da zero.

Per l'agent simulator: creare un file `.env` nella root del progetto con
`AGENTABILE_API_KEY=sk-ant-...` (mai committarlo — è in `.gitignore`).

## Plugin WordPress (`wordpress-plugin/agentabile/`)

Porting **PHP puro** (nessuna dipendenza da Python a runtime) di
model.py + connectors/woocommerce.py + exporters/acp.py, pensato per
girare su qualunque hosting WordPress.org — incluso condiviso, dove
Python e `shell_exec` tipicamente non sono disponibili.

- `agentabile.php` — bootstrap del plugin, verifica che WooCommerce sia
  attivo prima di agganciare qualunque funzionalità.
- `includes/Mapper.php` — `WC_Product`/`WC_Product_Variation` → modello
  canonico (array associativi). A differenza del connettore Python (REST
  API + OAuth 1.0a, gira fuori da WordPress) qui l'accesso è diretto agli
  oggetti WooCommerce, nessuna chiamata HTTP. Stessa copertura: prodotti
  "simple"/"variable", brand (tassonomia `product_brand` o attributo
  Brand/Marca), barcode (`get_global_unique_id()`), categorie gerarchiche.
- `includes/AcpExporter.php` — modello canonico → feed ACP 2026-04-17,
  stessa logica di `acp.py` (categorie propagate alle varianti,
  `additionalProperties: false` rispettato emettendo solo campi previsti).
- `includes/FeedController.php` — endpoint pubblico
  `GET /wp-json/agentabile/v1/feed/acp`.

**Testato end-to-end contro l'istanza WooCommerce reale** (stessa usata
per il connettore Python): plugin installato e attivato via wp-cli, feed
scaricato via HTTP dall'endpoint REST reale, **validato con lo stesso
validatore Python (`agentabile.validate.validate_acp_products`) usato per
l'exporter di riferimento — conforme allo schema ufficiale**. Prova
incrociata che il porting PHP produce un feed equivalente a quello Python.

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
7. ~~Fase 2 — **Plugin WordPress.org** (canale di distribuzione primario):
   wrapper PHP che chiama il motore Python o riimplementa l'export feed.~~
   **Fatto** — riimplementato in PHP puro (non wrapper: WordPress.org
   hosting condiviso tipicamente non ha Python/`shell_exec`). Scope v0.1:
   solo WooCommerce → feed ACP. Merchant Center e altri connettori restano
   da portare in una versione successiva del plugin.

## Vincoli di progetto

- Il modello canonico è stabile; gli exporter sono adapter usa-e-getta
  (le spec ACP cambiano ogni ~6 settimane: aggiornare `schemas/` e adapter).
- Niente checkout/payment in fase 1.
- `Money.minor_units()` assume valute a 2 decimali — da estendere se
  servono JPY/KWD.
