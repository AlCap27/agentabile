<?php
namespace AgentReady;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Endpoint pubblico che serve il feed ACP:
 * GET /wp-json/agentready/v1/feed/acp
 */
class FeedController {

	const CACHE_KEY = 'agentready_acp_feed';
	const CACHE_TTL = 5 * MINUTE_IN_SECONDS;

	public static function init(): void {
		add_action( 'rest_api_init', array( self::class, 'register_routes' ) );
		// Il feed dipende dai prodotti: invalida la cache quando cambiano,
		// invece di aspettare la scadenza del transient.
		add_action( 'save_post_product', array( self::class, 'invalidate_cache' ) );
		add_action( 'woocommerce_update_product', array( self::class, 'invalidate_cache' ) );
		add_action( 'woocommerce_delete_product', array( self::class, 'invalidate_cache' ) );
	}

	public static function register_routes(): void {
		register_rest_route(
			'agentready/v1',
			'/feed/acp',
			array(
				'methods'             => 'GET',
				'callback'            => array( self::class, 'serve_acp_feed' ),
				'permission_callback' => '__return_true', // feed pubblico, come un normale product feed.
			)
		);
	}

	public static function invalidate_cache(): void {
		delete_transient( self::CACHE_KEY );
	}

	public static function serve_acp_feed(): \WP_REST_Response {
		$feed = get_transient( self::CACHE_KEY );

		if ( false === $feed ) {
			$feed = self::build_feed();
			set_transient( self::CACHE_KEY, $feed, self::CACHE_TTL );
		}

		$response = new \WP_REST_Response( $feed );
		$response->header( 'Cache-Control', 'public, max-age=' . self::CACHE_TTL );
		return $response;
	}

	private static function build_feed(): array {
		$products = wc_get_products(
			array(
				'status' => 'publish',
				'limit'  => -1,
			)
		);

		// wc_get_products() non inoltra un 'tax_query' grezzo a WP_Query
		// (WC_Product_Data_Store_CPT::get_wp_query_args() ricostruisce la
		// query da zero a partire da var dedicate — un tax_query passato
		// direttamente viene silenziosamente ignorato). Si filtra quindi
		// sull'oggetto prodotto già caricato: esclude solo i prodotti con
		// visibilità "Nascosto" (stato ancora "publish", ma il merchant li
		// ha esplicitamente rimossi da catalogo E ricerca — non devono
		// comparire nel feed pubblico). "Solo negozio"/"Solo ricerca"
		// restano inclusi.
		$products = array_filter(
			$products,
			static function ( \WC_Product $product ): bool {
				return 'hidden' !== $product->get_catalog_visibility();
			}
		);

		$canonical   = Mapper::map_all_products( $products );
		$seller_name = get_bloginfo( 'name' );
		return AcpExporter::catalog_to_acp( $canonical, $seller_name );
	}
}
