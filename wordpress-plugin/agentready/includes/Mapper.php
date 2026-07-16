<?php
namespace AgentReady;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Mappa i prodotti WooCommerce nel modello canonico (array associativi),
 * porting PHP di agentready/connectors/woocommerce.py. A differenza del
 * connettore Python — che parla con WooCommerce via REST API + OAuth 1.0a
 * perché gira fuori da WordPress — qui il plugin vive dentro WordPress e
 * accede direttamente agli oggetti WC_Product: nessuna chiamata HTTP.
 *
 * Copertura: prodotti "simple" e "variable" (+ varianti). "grouped" ed
 * "external" non sono ancora supportati, come nel connettore Python.
 */
class Mapper {

	const STOCK_STATUS_MAP = array(
		'instock'     => 'in_stock',
		'outofstock'  => 'out_of_stock',
		'onbackorder' => 'backorder',
	);

	/**
	 * @param \WC_Product[] $wc_products
	 * @return array<int, array>
	 */
	public static function map_all_products( array $wc_products ): array {
		$out = array();
		foreach ( $wc_products as $wc_product ) {
			$mapped = self::map_product( $wc_product );
			if ( null !== $mapped ) {
				$out[] = $mapped;
			}
		}
		return $out;
	}

	public static function map_product( \WC_Product $product ) {
		$type = $product->get_type();
		if ( ! in_array( $type, array( 'simple', 'variable' ), true ) ) {
			return null;
		}

		if ( 'variable' === $type ) {
			$variants = array();
			foreach ( $product->get_children() as $variation_id ) {
				$variation = wc_get_product( $variation_id );
				if ( $variation instanceof \WC_Product_Variation && $variation->exists() ) {
					$variants[] = self::map_variant( $variation, $product );
				}
			}
			if ( empty( $variants ) ) {
				return null;
			}
		} else {
			$variants = array( self::map_variant( $product, $product ) );
		}

		return array(
			'id'                 => self::stable_id( $product ),
			'title'              => $product->get_name(),
			'brand'              => self::brand( $product ),
			'description_plain'  => self::plain_text( $product->get_short_description() ),
			'description_html'   => $product->get_description() ? $product->get_description() : null,
			'url'                => get_permalink( $product->get_id() ) ? get_permalink( $product->get_id() ) : null,
			'categories'         => self::categories( $product ),
			'media'              => self::media( $product ),
			'variants'           => $variants,
		);
	}

	private static function map_variant( \WC_Product $variant, \WC_Product $parent ): array {
		$price      = self::money( $variant->get_price() );
		$regular    = self::money( $variant->get_regular_price() );
		$list_price = null;
		if ( $regular && $price && $regular['amount'] > $price['amount'] ) {
			$list_price = $regular;
		}

		$description = $variant instanceof \WC_Product_Variation
			? $variant->get_description()
			: '';

		return array(
			'id'                 => self::stable_id( $variant ),
			'title'              => $variant->get_name() ? $variant->get_name() : $parent->get_name(),
			'description_plain'  => self::plain_text( (string) $description ),
			'url'                => get_permalink( $variant->get_id() ) ? get_permalink( $variant->get_id() ) : get_permalink( $parent->get_id() ),
			'barcodes'           => self::barcodes( $variant ),
			'price'              => $price,
			'list_price'         => $list_price,
			'availability'       => self::availability( $variant ),
			'condition'          => 'new',
			'options'            => self::variant_options( $variant ),
			'media'              => self::media( $variant ),
		);
	}

	private static function stable_id( \WC_Product $product ): string {
		$sku = trim( (string) $product->get_sku() );
		return '' !== $sku ? $sku : 'wc-' . $product->get_id();
	}

	private static function money( $raw ) {
		if ( null === $raw || '' === $raw ) {
			return null;
		}
		$amount = (float) $raw;
		if ( $amount < 0 ) {
			return null;
		}
		return array(
			'amount'   => round( $amount, 2 ),
			'currency' => get_woocommerce_currency(),
		);
	}

	private static function availability( \WC_Product $product ): array {
		$status = isset( self::STOCK_STATUS_MAP[ $product->get_stock_status() ] )
			? self::STOCK_STATUS_MAP[ $product->get_stock_status() ]
			: 'in_stock';
		return array(
			'available' => in_array( $status, array( 'in_stock', 'backorder' ), true ),
			'status'    => $status,
			'quantity'  => $product->get_manage_stock() ? $product->get_stock_quantity() : null,
		);
	}

	private static function barcodes( \WC_Product $product ): array {
		if ( ! method_exists( $product, 'get_global_unique_id' ) ) {
			return array();
		}
		$gtin = trim( (string) $product->get_global_unique_id() );
		if ( '' === $gtin ) {
			return array();
		}
		return array( array( 'type' => 'gtin', 'value' => $gtin ) );
	}

	private static function brand( \WC_Product $product ) {
		if ( taxonomy_exists( 'product_brand' ) ) {
			$terms = get_the_terms( $product->get_id(), 'product_brand' );
			if ( is_array( $terms ) && ! empty( $terms ) ) {
				return $terms[0]->name;
			}
		}
		foreach ( $product->get_attributes() as $attribute ) {
			$label = strtolower( trim( wc_attribute_label( $attribute->get_name(), $product ) ) );
			if ( in_array( $label, array( 'brand', 'marca' ), true ) ) {
				$options = $attribute->get_options();
				if ( ! empty( $options ) ) {
					$first = $options[0];
					if ( is_numeric( $first ) ) {
						$term = get_term( $first );
						return ( $term && ! is_wp_error( $term ) ) ? $term->name : null;
					}
					return (string) $first;
				}
			}
		}
		return null;
	}

	private static function categories( \WC_Product $product ): array {
		$terms = get_the_terms( $product->get_id(), 'product_cat' );
		if ( ! is_array( $terms ) || empty( $terms ) ) {
			return array();
		}
		$out = array();
		foreach ( $terms as $term ) {
			$out[] = array(
				'value'    => self::category_path( $term ),
				'taxonomy' => 'woocommerce',
			);
		}
		return $out;
	}

	private static function category_path( \WP_Term $term ): string {
		$path      = array( $term->name );
		$ancestors = get_ancestors( $term->term_id, 'product_cat' );
		foreach ( array_reverse( $ancestors ) as $ancestor_id ) {
			$ancestor = get_term( $ancestor_id, 'product_cat' );
			if ( $ancestor && ! is_wp_error( $ancestor ) ) {
				array_unshift( $path, $ancestor->name );
			}
		}
		return implode( ' > ', $path );
	}

	private static function media( \WC_Product $product ): array {
		$ids = array_filter( array_merge( array( $product->get_image_id() ), $product->get_gallery_image_ids() ) );
		$out = array();
		foreach ( $ids as $id ) {
			$url = wp_get_attachment_image_url( $id, 'full' );
			if ( $url ) {
				$alt = get_post_meta( $id, '_wp_attachment_image_alt', true );
				$out[] = array(
					'type'     => 'image',
					'url'      => $url,
					'alt_text' => $alt ? $alt : null,
				);
			}
		}
		return $out;
	}

	private static function variant_options( \WC_Product $product ): array {
		if ( ! $product instanceof \WC_Product_Variation ) {
			return array();
		}
		$out = array();
		foreach ( $product->get_variation_attributes() as $attribute_name => $value ) {
			if ( '' === $value ) {
				continue;
			}
			$taxonomy_or_name = str_replace( 'attribute_', '', $attribute_name );
			$label            = wc_attribute_label( $taxonomy_or_name );
			$out[]            = array(
				'name'  => $label,
				'value' => self::term_name_or_value( $taxonomy_or_name, $value ),
			);
		}
		return $out;
	}

	private static function term_name_or_value( string $taxonomy_or_name, string $value ): string {
		if ( taxonomy_exists( $taxonomy_or_name ) ) {
			$term = get_term_by( 'slug', $value, $taxonomy_or_name );
			if ( $term ) {
				return $term->name;
			}
		}
		return $value;
	}

	private static function plain_text( string $html ) {
		$text = trim( wp_strip_all_tags( $html ) );
		return '' !== $text ? $text : null;
	}
}
