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

	public static function init(): void {
		add_action( 'rest_api_init', array( self::class, 'register_routes' ) );
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

	public static function serve_acp_feed(): \WP_REST_Response {
		$products = wc_get_products(
			array(
				'status' => 'publish',
				'limit'  => -1,
			)
		);

		$canonical   = Mapper::map_all_products( $products );
		$seller_name = get_bloginfo( 'name' );
		$feed        = AcpExporter::catalog_to_acp( $canonical, $seller_name );

		$response = new \WP_REST_Response( $feed );
		$response->header( 'Cache-Control', 'public, max-age=300' );
		return $response;
	}
}
