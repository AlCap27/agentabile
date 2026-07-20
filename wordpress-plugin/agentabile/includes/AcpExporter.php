<?php
namespace Agentabile;

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

/**
 * Export canonico -> ACP feed 2026-04-17, porting PHP di
 * agentabile/exporters/acp.py. Stessa regola chiave: lo schema ufficiale ha
 * additionalProperties:false ovunque, quindi si emettono SOLO campi previsti.
 */
class AcpExporter {

	public static function catalog_to_acp( array $products, string $seller_name ): array {
		$out = array();
		foreach ( $products as $product ) {
			$out[] = self::product_to_acp( $product, $seller_name );
		}
		return $out;
	}

	private static function product_to_acp( array $product, string $seller_name ): array {
		$variants = array();
		foreach ( $product['variants'] as $variant ) {
			$variants[] = self::variant_to_acp( $variant, $seller_name );
		}

		$out = array(
			'id'       => $product['id'],
			'variants' => $variants,
		);

		if ( ! empty( $product['title'] ) ) {
			$out['title'] = $product['title'];
		}

		$description = array();
		if ( ! empty( $product['description_plain'] ) ) {
			$description['plain'] = $product['description_plain'];
		}
		if ( ! empty( $product['description_html'] ) ) {
			$description['html'] = $product['description_html'];
		}
		if ( ! empty( $description ) ) {
			$out['description'] = $description;
		}

		if ( ! empty( $product['url'] ) ) {
			$out['url'] = $product['url'];
		}

		if ( ! empty( $product['media'] ) ) {
			$out['media'] = array_map( array( self::class, 'media_to_acp' ), $product['media'] );
		}

		// Le categorie canoniche di prodotto vengono propagate alle varianti,
		// come nell'exporter Python (nella spec ACP feed vivono a livello Variant).
		if ( ! empty( $product['categories'] ) ) {
			$categories = array();
			foreach ( $product['categories'] as $category ) {
				$entry = array( 'value' => $category['value'] );
				if ( ! empty( $category['taxonomy'] ) ) {
					$entry['taxonomy'] = $category['taxonomy'];
				}
				$categories[] = $entry;
			}
			foreach ( $out['variants'] as &$variant_ref ) {
				$variant_ref['categories'] = $categories;
			}
			unset( $variant_ref );
		}

		return $out;
	}

	private static function variant_to_acp( array $variant, string $seller_name ): array {
		$out = array(
			'id'    => $variant['id'],
			'title' => $variant['title'],
		);

		if ( ! empty( $variant['description_plain'] ) ) {
			$out['description'] = array( 'plain' => $variant['description_plain'] );
		}
		if ( ! empty( $variant['url'] ) ) {
			$out['url'] = $variant['url'];
		}
		if ( ! empty( $variant['barcodes'] ) ) {
			$out['barcodes'] = $variant['barcodes'];
		}
		if ( ! empty( $variant['price'] ) ) {
			$out['price'] = self::money_to_acp( $variant['price'] );
		}
		if ( ! empty( $variant['list_price'] ) ) {
			$out['list_price'] = self::money_to_acp( $variant['list_price'] );
		}

		$availability        = $variant['availability'];
		$out['availability'] = array(
			'available' => $availability['available'],
			'status'    => $availability['status'],
		);

		if ( ! empty( $variant['condition'] ) ) {
			$out['condition'] = array( $variant['condition'] );
		}
		if ( ! empty( $variant['options'] ) ) {
			$out['variant_options'] = $variant['options'];
		}
		if ( ! empty( $variant['media'] ) ) {
			$out['media'] = array_map( array( self::class, 'media_to_acp' ), $variant['media'] );
		}

		$out['seller'] = array( 'name' => $seller_name );

		return $out;
	}

	private static function money_to_acp( array $money ): array {
		return array(
			'amount'   => self::minor_units( $money['amount'] ),
			'currency' => $money['currency'],
		);
	}

	private static function minor_units( float $amount ): int {
		// Assume valute a 2 decimali — stesso limite documentato di
		// Money.minor_units() nel modello Python, da estendere se servono JPY/KWD.
		return (int) round( $amount * 100 );
	}

	private static function media_to_acp( array $media ): array {
		$out = array(
			'type' => $media['type'],
			'url'  => $media['url'],
		);
		if ( ! empty( $media['alt_text'] ) ) {
			$out['alt_text'] = $media['alt_text'];
		}
		return $out;
	}
}
