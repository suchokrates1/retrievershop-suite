<?php
/**
 * Pobierz zdjecia Allegro i podlacz do produktu Woo.
 * Usage:
 *   wp eval-file _wp_upload_allegro_images.php --allow-root
 * Env:
 *   WOO_PRODUCT_ID=3422
 *   IMAGE_URLS=url1|url2|url3
 */
if (!defined('ABSPATH')) {
    exit(1);
}

require_once ABSPATH . 'wp-admin/includes/file.php';
require_once ABSPATH . 'wp-admin/includes/media.php';
require_once ABSPATH . 'wp-admin/includes/image.php';

$product_id = intval(getenv('WOO_PRODUCT_ID') ?: 0);
$urls_raw = getenv('IMAGE_URLS') ?: '';
$urls = array_values(array_filter(array_map('trim', explode('|', $urls_raw))));

if (!$product_id || !$urls) {
    fwrite(STDERR, "Need WOO_PRODUCT_ID and IMAGE_URLS\n");
    exit(1);
}

$product = wc_get_product($product_id);
if (!$product) {
    fwrite(STDERR, "Product {$product_id} not found\n");
    exit(1);
}

$attachment_ids = array();
foreach ($urls as $idx => $url) {
    $tmp = download_url($url, 60);
    if (is_wp_error($tmp)) {
        echo "download_fail idx={$idx} err=" . $tmp->get_error_message() . "\n";
        continue;
    }

    // Allegro URL bez rozszerzenia — wymus jpg
    $filename = sprintf('allegro_%d_%d.jpg', $product_id, $idx);
    $file_array = array(
        'name' => $filename,
        'tmp_name' => $tmp,
        'type' => 'image/jpeg',
    );

    $attach_id = media_handle_sideload($file_array, $product_id);
    if (is_wp_error($attach_id)) {
        @unlink($tmp);
        echo "upload_fail idx={$idx} err=" . $attach_id->get_error_message() . "\n";
        continue;
    }
    $attachment_ids[] = intval($attach_id);
    echo "uploaded idx={$idx} attachment_id={$attach_id}\n";
}

if (!$attachment_ids) {
    fwrite(STDERR, "No images uploaded\n");
    exit(2);
}

$product->set_image_id($attachment_ids[0]);
if (count($attachment_ids) > 1) {
    $product->set_gallery_image_ids(array_slice($attachment_ids, 1));
}
$product->save();

echo "attached product={$product_id} featured={$attachment_ids[0]} gallery=" . implode(',', array_slice($attachment_ids, 1)) . "\n";
