<?php
namespace Agentabile;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Endpoint pubblico che serve il feed ACP:
 * GET /wp-json/agentabile/v1/feed/acp
 */
class FeedController {

	const CACHE_KEY  = 'agentabile_acp_feed';
	const CACHE_TTL  = 5 * MINUTE_IN_SECONDS;
	const BATCH_SIZE = 100;

	public static function init(): void {
		add_action( 'rest_api_init', array( self::class, 'register_routes' ) );
		// Il feed dipende dai prodotti: invalida la cache quando cambiano,
		// invece di aspettare la scadenza del transient.
		add_action( 'save_post_product', array( self::class, 'invalidate_cache' ) );
		add_action( 'woocommerce_update_product', array( self::class, 'invalidate_cache' ) );
		add_action( 'woocommerce_delete_product', array( self::class, 'invalidate_cache' ) );
		// Le varianti (prodotti "variation") non passano per save_post_product,
		// e le modifiche di stock hanno hook dedicati: senza questi, cambi su
		// varianti/stock resterebbero invisibili fino alla scadenza del transient.
		add_action( 'woocommerce_update_product_variation', array( self::class, 'invalidate_cache' ) );
		add_action( 'woocommerce_save_product_variation', array( self::class, 'invalidate_cache' ) );
		add_action( 'woocommerce_delete_product_variation', array( self::class, 'invalidate_cache' ) );
		add_action( 'woocommerce_product_set_stock', array( self::class, 'invalidate_cache' ) );
		add_action( 'woocommerce_variation_set_stock', array( self::class, 'invalidate_cache' ) );
	}

	public static function register_routes(): void {
		register_rest_route(
			'agentabile/v1',
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

	// Niente type hint di ritorno: il plugin dichiara "Requires PHP: 7.4" e
	// qui si può tornare sia WP_REST_Response sia WP_Error — un union type
	// (WP_REST_Response|WP_Error) richiederebbe PHP 8.0+.
	public static function serve_acp_feed() {
		try {
			$feed = get_transient( self::CACHE_KEY );

			if ( false === $feed ) {
				$feed = self::build_feed();
				set_transient( self::CACHE_KEY, $feed, self::CACHE_TTL );
			}

			$response = new \WP_REST_Response( $feed );
			$response->header( 'Cache-Control', 'public, max-age=' . self::CACHE_TTL );
			return $response;
		} catch ( \Throwable $e ) {
			error_log( 'Agentabile: errore nella generazione del feed ACP: ' . $e->getMessage() );
			return new \WP_Error( 'agentabile_feed_error', 'Errore nella generazione del feed.', array( 'status' => 500 ) );
		}
	}

	private static function build_feed(): array {
		// Paginazione a blocchi di BATCH_SIZE, stessa convenzione del connettore
		// Python (get_products()): evita di caricare l'intero catalogo in un
		// solo colpo su store con molti prodotti.
		$products = array();
		$page     = 1;
		do {
			$batch = wc_get_products(
				array(
					'status' => 'publish',
					'limit'  => self::BATCH_SIZE,
					'page'   => $page,
				)
			);
			$products = array_merge( $products, $batch );
			$page++;
		} while ( count( $batch ) === self::BATCH_SIZE );

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
