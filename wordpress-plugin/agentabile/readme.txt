=== Agentabile – AI Agent Readiness for WooCommerce (ACP, UCP, MCP) ===
Contributors: gilles27
Tags: woocommerce, ai, agentic commerce, acp, feed
Requires at least: 6.0
Tested up to: 7.0
Requires PHP: 7.4
Stable tag: 0.1.0
License: GPLv2 or later
License URI: https://www.gnu.org/licenses/gpl-2.0.html

Exposes your WooCommerce catalog as an ACP (Agentic Commerce Protocol) feed, readable by AI agents. Pure PHP, no external runtime dependencies.

== Description ==

Agentabile automatically generates a product feed compliant with the Agentic Commerce Protocol (ACP) from your WooCommerce catalog, available at:

`/wp-json/agentabile/v1/feed/acp`

No configuration required: just activate the plugin with WooCommerce active. The mapping from WooCommerce to the canonical model and the feed export are entirely written in PHP — no Python runtime or external dependency, works on any standard WordPress hosting.

== Installation ==

1. Upload the `agentabile` folder to `/wp-content/plugins/`.
2. Activate the plugin from the WordPress Plugins menu.
3. Make sure WooCommerce is installed and active.
4. The feed is available at `https://yoursite.com/wp-json/agentabile/v1/feed/acp`.

== Frequently Asked Questions ==

= Do I need Python or other dependencies? =

No. The plugin is written entirely in PHP and runs on any standard WordPress hosting, including shared hosting.

= Which product types are supported? =

"Simple" and "variable" products, including their variations. "Grouped" and "external" products are not yet supported.

= Is the feed compatible with the official ACP schema? =

Yes — the feed structure exactly replicates the Agentabile project's reference exporter (Python), validated against the official Agentic Commerce Protocol JSON schema.

== Screenshots ==

== Changelog ==

= 0.1.0 =
* First release: WooCommerce to canonical model mapping, ACP feed export via REST API.
