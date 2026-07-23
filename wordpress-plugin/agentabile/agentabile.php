<?php
/**
 * Plugin Name:       Agentabile – AI Agent Readiness for E-Commerce (ACP, UCP, MCP)
 * Plugin URI:        https://agentabile.dev
 * Description:       Espone il catalogo WooCommerce come feed ACP (Agentic Commerce Protocol), leggibile dagli agenti AI. PHP puro, nessuna dipendenza da runtime esterni.
 * Version:           0.1.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            Agentabile
 * Author URI:        https://agentabile.dev
 * License:           GPL-2.0-or-later
 * License URI:       https://www.gnu.org/licenses/gpl-2.0.html
 * Text Domain:       agentabile
 * Requires Plugins:  woocommerce
 */

namespace Agentabile;

if ( ! defined( 'ABSPATH' ) ) {
	exit; // Niente accesso diretto.
}

define( 'AGENTABILE_VERSION', '0.1.0' );
define( 'AGENTABILE_PLUGIN_DIR', plugin_dir_path( __FILE__ ) );

require_once AGENTABILE_PLUGIN_DIR . 'includes/Mapper.php';
require_once AGENTABILE_PLUGIN_DIR . 'includes/AcpExporter.php';
require_once AGENTABILE_PLUGIN_DIR . 'includes/FeedController.php';

/**
 * Aggancia le funzionalità del plugin solo se WooCommerce è attivo — nessuna
 * dipendenza Python/esterna: il porting di model.py/woocommerce.py/acp.py
 * è interamente PHP, pensato per girare su hosting condiviso WordPress.org.
 */
function bootstrap() {
	if ( ! class_exists( 'WooCommerce' ) ) {
		add_action( 'admin_notices', __NAMESPACE__ . '\\missing_woocommerce_notice' );
		return;
	}

	FeedController::init();
}
add_action( 'plugins_loaded', __NAMESPACE__ . '\\bootstrap' );

function missing_woocommerce_notice() {
	echo '<div class="notice notice-error"><p>';
	esc_html_e( 'Agentabile richiede WooCommerce attivo per funzionare.', 'agentabile' );
	echo '</p></div>';
}
