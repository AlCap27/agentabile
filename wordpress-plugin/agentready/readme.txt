=== AgentReady per WooCommerce ===
Contributors: agentready
Tags: woocommerce, ai, agentic commerce, acp, feed
Requires at least: 6.0
Tested up to: 6.7
Requires PHP: 7.4
Stable tag: 0.1.0
License: AGPLv3 or later
License URI: https://www.gnu.org/licenses/agpl-3.0.html

Espone il catalogo WooCommerce come feed ACP (Agentic Commerce Protocol), leggibile dagli agenti AI. PHP puro, nessuna dipendenza da runtime esterni.

== Description ==

AgentReady genera automaticamente un feed prodotto conforme alla Agentic Commerce Protocol (ACP) a partire dal tuo catalogo WooCommerce, disponibile su:

`/wp-json/agentready/v1/feed/acp`

Nessuna configurazione richiesta: basta attivare il plugin con WooCommerce attivo. Il mapping da WooCommerce al modello canonico e l'export del feed sono interamente in PHP — nessun runtime Python o dipendenza esterna, funziona su qualunque hosting WordPress standard.

== Installation ==

1. Carica la cartella `agentready` in `/wp-content/plugins/`.
2. Attiva il plugin dal menu Plugin di WordPress.
3. Assicurati che WooCommerce sia installato e attivo.
4. Il feed è disponibile a `https://tuosito.it/wp-json/agentready/v1/feed/acp`.

== Frequently Asked Questions ==

= Serve Python o altre dipendenze? =

No. Il plugin è scritto interamente in PHP e gira su qualunque hosting WordPress standard, incluso condiviso.

= Quali tipi di prodotto sono supportati? =

Prodotti "simple" e "variable" con le relative varianti. Prodotti "grouped" ed "external" non sono ancora supportati.

= Il feed è compatibile con lo schema ACP ufficiale? =

Sì — la struttura del feed replica esattamente l'exporter di riferimento del progetto AgentReady (Python), validato contro lo schema JSON ufficiale della Agentic Commerce Protocol.

== Changelog ==

= 0.1.0 =
* Prima versione: mapping WooCommerce -> modello canonico, export feed ACP via REST API.
