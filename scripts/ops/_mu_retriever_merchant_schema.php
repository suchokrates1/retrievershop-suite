<?php
/**
 * Plugin Name: Retriever Merchant Schema
 * Description: Uzupełnia Product/Offer JSON-LD o brand, GTIN, shippingDetails, return policy, validFrom (GSC Merchant).
 */
if (!defined('ABSPATH')) {
    exit;
}

/**
 * @return array{value:float,currency:string,label:string,min_handling:int,max_handling:int,min_transit:int,max_transit:int}
 */
function rs_merchant_shipping_defaults(): array {
    return [
        'value' => 0.0,
        'currency' => get_woocommerce_currency() ?: 'PLN',
        'label' => 'InPost Paczkomat / Kurier',
        'min_handling' => 0,
        'max_handling' => 1,
        'min_transit' => 1,
        'max_transit' => 2,
    ];
}

function rs_merchant_return_policy(): array {
    return [
        '@type' => 'MerchantReturnPolicy',
        '@id' => home_url('/zwroty/#policy'),
        'applicableCountry' => 'PL',
        'returnPolicyCategory' => 'https://schema.org/MerchantReturnFiniteReturnWindow',
        'merchantReturnDays' => 14,
        'returnMethod' => 'https://schema.org/ReturnByMail',
        'returnFees' => 'https://schema.org/ReturnFeesCustomerResponsibility',
        'url' => home_url('/zwroty/'),
    ];
}

function rs_merchant_shipping_details(): array {
    $d = rs_merchant_shipping_defaults();
    $base = [
        '@type' => 'OfferShippingDetails',
        'shippingDestination' => [
            '@type' => 'DefinedRegion',
            'addressCountry' => 'PL',
        ],
        'deliveryTime' => [
            '@type' => 'ShippingDeliveryTime',
            'handlingTime' => [
                '@type' => 'QuantitativeValue',
                'minValue' => $d['min_handling'],
                'maxValue' => $d['max_handling'],
                'unitCode' => 'DAY',
            ],
            'transitTime' => [
                '@type' => 'QuantitativeValue',
                'minValue' => $d['min_transit'],
                'maxValue' => $d['max_transit'],
                'unitCode' => 'DAY',
            ],
        ],
        'shippingRate' => [
            '@type' => 'MonetaryAmount',
            'value' => $d['value'],
            'currency' => $d['currency'],
        ],
    ];
    // Two free options (same rate) — paczkomat + kurier
    $pacz = $base;
    $pacz['@id'] = home_url('/#shipping-inpost-paczkomat');
    $kurier = $base;
    $kurier['@id'] = home_url('/#shipping-inpost-kurier');
    return [$pacz, $kurier];
}

function rs_merchant_is_gtin(string $code): bool {
    $code = preg_replace('/\D+/', '', $code);
    $len = strlen($code);
    if (!in_array($len, [8, 12, 13, 14], true)) {
        return false;
    }
    // GS1 check digit
    $digits = array_map('intval', str_split($code));
    $check = array_pop($digits);
    $sum = 0;
    $parity = count($digits) % 2; // for GTIN-13: odd positions from right weight 3
    for ($i = count($digits) - 1, $pos = 0; $i >= 0; $i--, $pos++) {
        $sum += $digits[$i] * (($pos % 2 === 0) ? 3 : 1);
    }
    $calc = (10 - ($sum % 10)) % 10;
    return $calc === $check;
}

function rs_merchant_product_brand(WC_Product $product): string {
    $brand = trim((string) $product->get_attribute('pa_marka'));
    if ($brand === '') {
        $brand = trim((string) $product->get_attribute('marka'));
    }
    if ($brand === '' && taxonomy_exists('product_brand')) {
        $terms = get_the_terms($product->get_id(), 'product_brand');
        if (is_array($terms) && $terms) {
            $brand = (string) $terms[0]->name;
        }
    }
    return $brand !== '' ? $brand : 'Truelove';
}

/**
 * Prefer in-stock variation EAN/SKU as GTIN when valid.
 */
function rs_merchant_product_gtin(WC_Product $product): string {
    $candidates = [];
    if ($product->is_type('variable')) {
        foreach ($product->get_children() as $vid) {
            $v = wc_get_product($vid);
            if (!$v) {
                continue;
            }
            $sku = (string) $v->get_sku();
            if ($sku !== '') {
                $candidates[] = $sku;
            }
            if (method_exists($v, 'get_global_unique_id')) {
                $g = (string) $v->get_global_unique_id();
                if ($g !== '') {
                    array_unshift($candidates, $g);
                }
            }
        }
    }
    $sku = (string) $product->get_sku();
    if ($sku !== '') {
        $candidates[] = $sku;
    }
    if (method_exists($product, 'get_global_unique_id')) {
        $g = (string) $product->get_global_unique_id();
        if ($g !== '') {
            array_unshift($candidates, $g);
        }
    }
    foreach ($candidates as $c) {
        $digits = preg_replace('/\D+/', '', (string) $c);
        if (rs_merchant_is_gtin($digits)) {
            return $digits;
        }
    }
    return '';
}

function rs_merchant_offer_valid_from(WC_Product $product): string {
    $ts = $product->get_date_created() ? $product->get_date_created()->getTimestamp() : time();
    return gmdate('c', $ts);
}

/**
 * Google Merchant: sku Text, no whitespace, ASCII preferred, length 1–100
 * (GSC "invalid string length" often = empty / too long / non-text).
 */
function rs_merchant_normalize_sku(WC_Product $product, $current = null): string {
    if (is_array($current)) {
        $current = reset($current);
    }
    $candidates = [
        is_string($current) || is_numeric($current) ? (string) $current : '',
        (string) $product->get_sku(),
        'RS-' . $product->get_id(),
    ];
    foreach ($candidates as $raw) {
        $sku = preg_replace('/\s+/u', '', trim((string) $raw));
        $sku = preg_replace('/[^A-Za-z0-9._\\-]/', '', $sku);
        if ($sku === '' || $sku === '0') {
            continue;
        }
        // Prefer merchant-style ids under 70 chars (safe for GSC + feeds).
        if (strlen($sku) > 70) {
            $sku = substr($sku, 0, 70);
        }
        if (strlen($sku) >= 1 && strlen($sku) <= 100) {
            return $sku;
        }
    }
    return 'RS-' . $product->get_id();
}

function rs_merchant_enrich_price_specification($price_spec, string $valid_from, ?string $valid_through = null) {
    if (!is_array($price_spec)) {
        return $price_spec;
    }
    $apply = static function (array $row) use ($valid_from, $valid_through): array {
        if (empty($row['validFrom'])) {
            $row['validFrom'] = $valid_from;
        }
        if ($valid_through && empty($row['validThrough']) && empty($row['priceValidUntil'])) {
            $row['validThrough'] = $valid_through;
        }
        return $row;
    };
    // Single object
    if (isset($price_spec['@type']) || isset($price_spec['price']) || isset($price_spec['priceCurrency'])) {
        return $apply($price_spec);
    }
    foreach ($price_spec as $i => $row) {
        if (is_array($row)) {
            $price_spec[$i] = $apply($row);
        }
    }
    return $price_spec;
}

/**
 * Build UnitPriceSpecification when Woo emits AggregateOffer without one.
 * GSC Merchant: missing validFrom inside offers.priceSpecification.
 */
function rs_merchant_build_price_specification(array $offer, string $valid_from): array {
    $currency = $offer['priceCurrency'] ?? (get_woocommerce_currency() ?: 'PLN');
    $candidates = [
        $offer['price'] ?? null,
        $offer['lowPrice'] ?? null,
        $offer['highPrice'] ?? null,
    ];
    $price = null;
    foreach ($candidates as $c) {
        if ($c === null || $c === '') {
            continue;
        }
        if ((float) $c > 0) {
            $price = $c;
            break;
        }
        if ($price === null) {
            $price = $c;
        }
    }
    if ($price === null || $price === '') {
        $price = '0';
    }
    $through = $offer['priceValidUntil'] ?? $offer['validThrough'] ?? gmdate('Y-m-d', strtotime('+18 months'));
    return [
        [
            '@type' => 'UnitPriceSpecification',
            'price' => (string) $price,
            'priceCurrency' => (string) $currency,
            'validFrom' => $valid_from,
            'validThrough' => (string) $through,
        ],
    ];
}

function rs_merchant_enrich_offer(array $offer, WC_Product $product): array {
    $valid_from = rs_merchant_offer_valid_from($product);
    $valid_through = null;
    if (!empty($offer['priceValidUntil'])) {
        $valid_through = (string) $offer['priceValidUntil'];
    } elseif (!empty($offer['validThrough'])) {
        $valid_through = (string) $offer['validThrough'];
    } else {
        $valid_through = gmdate('Y-m-d', strtotime('+18 months'));
        if (empty($offer['priceValidUntil'])) {
            $offer['priceValidUntil'] = $valid_through;
        }
    }

    if (empty($offer['priceCurrency'])) {
        $offer['priceCurrency'] = get_woocommerce_currency() ?: 'PLN';
    }
    if (empty($offer['itemCondition'])) {
        $offer['itemCondition'] = 'https://schema.org/NewCondition';
    }
    if (empty($offer['validFrom'])) {
        $offer['validFrom'] = $valid_from;
    }
    if (empty($offer['priceSpecification'])) {
        $offer['priceSpecification'] = rs_merchant_build_price_specification($offer, $offer['validFrom']);
    } else {
        $offer['priceSpecification'] = rs_merchant_enrich_price_specification(
            $offer['priceSpecification'],
            $offer['validFrom'],
            $valid_through
        );
    }
    if (empty($offer['shippingDetails'])) {
        $offer['shippingDetails'] = rs_merchant_shipping_details();
    }
    if (empty($offer['hasMerchantReturnPolicy'])) {
        $offer['hasMerchantReturnPolicy'] = rs_merchant_return_policy();
    }
    if (empty($offer['seller']) || !is_array($offer['seller'])) {
        $offer['seller'] = [
            '@type' => 'Organization',
            'name' => 'Retriever Shop',
            'url' => home_url('/'),
        ];
    }
    return $offer;
}

add_filter('woocommerce_structured_data_product', static function (array $markup, $product) {
    if (!$product instanceof WC_Product) {
        return $markup;
    }

    // Always emit a valid string SKU (WC may fall back to numeric product ID).
    $markup['sku'] = rs_merchant_normalize_sku($product, $markup['sku'] ?? null);

    // Brand (satisfies "GTIN or brand")
    if (empty($markup['brand'])) {
        $markup['brand'] = [
            '@type' => 'Brand',
            'name' => rs_merchant_product_brand($product),
        ];
    }

    // GTIN when we have a valid EAN on variations/SKU
    $gtin = rs_merchant_product_gtin($product);
    if ($gtin !== '') {
        $len = strlen($gtin);
        $key = match ($len) {
            8 => 'gtin8',
            12 => 'gtin12',
            13 => 'gtin13',
            14 => 'gtin14',
            default => 'gtin',
        };
        if (empty($markup[$key]) && empty($markup['gtin'])) {
            $markup[$key] = $gtin;
        }
    } elseif (empty($markup['mpn'])) {
        $sku = (string) $product->get_sku();
        if ($sku !== '' && !preg_match('/^RS-\d+$/i', $sku)) {
            $markup['mpn'] = $sku;
        }
    }

    if (!empty($markup['offers'])) {
        $offers = $markup['offers'];
        if (isset($offers['@type'])) {
            $markup['offers'] = rs_merchant_enrich_offer($offers, $product);
        } elseif (is_array($offers)) {
            foreach ($offers as $i => $offer) {
                if (is_array($offer)) {
                    $markup['offers'][$i] = rs_merchant_enrich_offer($offer, $product);
                }
            }
        }
    }

    return $markup;
}, 40, 2);

/**
 * AIOSEO Organization + Product graphs (when AIOSEO emits Product alongside Woo).
 */
add_filter('aioseo_schema_output', static function ($graphs) {
    if (!is_array($graphs)) {
        return $graphs;
    }
    $product = null;
    if (function_exists('wc_get_product') && is_singular('product')) {
        $product = wc_get_product(get_queried_object_id());
    }
    foreach ($graphs as &$graph) {
        if (!is_array($graph)) {
            continue;
        }
        $type = $graph['@type'] ?? '';
        $types = is_array($type) ? $type : [$type];
        if (in_array('Organization', $types, true)) {
            if (empty($graph['hasMerchantReturnPolicy'])) {
                $graph['hasMerchantReturnPolicy'] = rs_merchant_return_policy();
            }
        }
        if ($product instanceof WC_Product && (in_array('Product', $types, true) || in_array('ProductGroup', $types, true))) {
            $graph['sku'] = rs_merchant_normalize_sku($product, $graph['sku'] ?? null);
            if (!empty($graph['offers'])) {
                $offers = $graph['offers'];
                if (isset($offers['@type'])) {
                    $graph['offers'] = rs_merchant_enrich_offer($offers, $product);
                } elseif (is_array($offers)) {
                    foreach ($offers as $i => $offer) {
                        if (is_array($offer)) {
                            $graph['offers'][$i] = rs_merchant_enrich_offer($offer, $product);
                        }
                    }
                }
            }
        }
    }
    unset($graph);
    return $graphs;
}, 20);
