# AgentReady

Toolkit open source per rendere i cataloghi delle PMI europee visibili e
comprensibili agli agenti AI (ACP, Google Merchant/UCP, MCP), senza
dipendere dall'auto-enrollment delle piattaforme proprietarie.

## Il problema

Il commercio si sta spostando dagli occhi umani agli agenti AI (ChatGPT
Shopping, Google AI Mode, assistenti su Claude/Copilot). I protocolli che
governano questa transizione — ACP (OpenAI/Stripe) e UCP (Google) —
auto-arruolano i merchant delle grandi piattaforme (Shopify, Walmart,
Etsy). Chi resta fuori: le PMI europee su WooCommerce, PrestaShop o
e-commerce custom, che diventano invisibili agli agenti non per qualità
dei prodotti ma per illeggibilità dei dati.

## La soluzione

Un motore di normalizzazione hub-and-spoke: un modello canonico stabile
verso cui convergono i connettori di ingestion e da cui divergono gli
exporter — così le spec esterne (che cambiano ogni ~6 settimane) toccano
solo gli adapter, mai il cuore del sistema.

## Struttura del repo

- **`agentready/`** — motore Python: modello canonico (pydantic),
  connettori (WooCommerce REST v3, CSV con wizard di column-mapping),
  exporter (ACP, Google Merchant Center), server MCP auto-generato
  (`search_products`, `get_product`, `check_availability`),
  Agent-Readiness Score, agent simulator (query reali via Claude API).
  Vedi [agentready/README.md](agentready/README.md) per i dettagli di
  ogni modulo, come eseguire i test e le variabili d'ambiente richieste.
- **`wordpress-plugin/agentready/`** — plugin WordPress (PHP puro,
  nessuna dipendenza da Python a runtime — pensato per l'hosting
  condiviso WordPress.org): espone il catalogo WooCommerce come feed ACP
  su `GET /wp-json/agentready/v1/feed/acp`. Vedi
  [wordpress-plugin/agentready/readme.txt](wordpress-plugin/agentready/readme.txt).

## Stato

MVP completo: modello canonico, connettori WooCommerce e CSV, exporter
ACP (validato contro lo schema JSON ufficiale) e Google Merchant Center,
server MCP, Agent-Readiness Score, agent simulator, plugin WordPress.
Ogni componente Python ha uno smoke test dedicato in `agentready/tests/`;
il plugin WordPress è stato validato end-to-end contro un'istanza
WooCommerce reale.

## Licenza

AGPL-3.0 — vedi [LICENSE](LICENSE).
