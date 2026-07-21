<?php
require '/var/www/html/wp-load.php';
wp_set_current_user(1);

// Ensure table
RS_Newsletter::maybe_create_table();
global $wpdb;
$table = RS_Newsletter::table_name();
echo "table=$table exists=" . ($wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table)) === $table ? '1' : '0') . "\n";

// Update Elementor shortcode widget to explicit shortcode
$raw = get_post_meta(595, '_elementor_data', true);
$data = json_decode($raw, true);
if (!is_array($data)) {
    echo "elementor json bad\n";
    exit(1);
}
$changed = 0;
$walk = function (&$els) use (&$walk, &$changed) {
    foreach ($els as &$el) {
        if (($el['widgetType'] ?? '') === 'shortcode') {
            $sc = $el['settings']['shortcode'] ?? '';
            if (stripos($sc, 'mailpoet_form') !== false) {
                $el['settings']['shortcode'] = '[rs_newsletter_form]';
                $changed++;
            }
        }
        if (!empty($el['elements'])) {
            $walk($el['elements']);
        }
    }
};
$walk($data);
$new = wp_json_encode($data);
if (!is_array(json_decode($new, true))) {
    echo "encode fail\n";
    exit(1);
}
update_post_meta(595, '_elementor_data', wp_slash($new));
delete_post_meta(595, '_elementor_css');
if (class_exists('\\Elementor\\Plugin')) {
    \Elementor\Plugin::$instance->files_manager->clear_cache();
}
echo "elementor_shortcode_updated=$changed\n";

// Also fix nearby copy 10zł -> 10% in elementor text if present
$raw2 = get_post_meta(595, '_elementor_data', true);
if (str_contains($raw2, '10z') || str_contains($raw2, '10 zł') || str_contains($raw2, '10zł')) {
    $raw2 = str_replace(['10zł', '10 zł', '10z\u0142'], '10%', $raw2);
    // careful - only if still valid json
    if (is_array(json_decode($raw2, true))) {
        update_post_meta(595, '_elementor_data', wp_slash($raw2));
        echo "copy_10zl_fixed\n";
    }
}

// Dry-run coupon create + delete
$code = 'RS10-TEST' . strtoupper(wp_generate_password(4, false, false));
$id = (new ReflectionClass('RS_Newsletter'))->getMethod('create_coupon');
$id->setAccessible(true);
$cid = $id->invoke(null, $code, 'test-newsletter@retrievershop.pl');
echo "test_coupon_id=$cid code=$code\n";
$c = new WC_Coupon($code);
echo "type={$c->get_discount_type()} amount={$c->get_amount()} limit={$c->get_usage_limit()} email=" . implode(',', $c->get_email_restrictions()) . "\n";
wp_delete_post($cid, true);
echo "test_coupon_deleted\n";

// Shortcode render smoke
$html = do_shortcode('[rs_newsletter_form]');
echo "form_has_email=" . (str_contains($html, 'type="email"') ? '1' : '0') . "\n";
echo "form_has_first=" . (str_contains($html, 'first_name') ? '1' : '0') . "\n";
echo "alias=" . (str_contains(do_shortcode('[mailpoet_form id="1"]'), 'rs-nl__form') ? '1' : '0') . "\n";

wp_cache_flush();
$s = WP_CONTENT_DIR . '/cache/seraphinite-accelerator/s';
if (is_dir($s)) {
    $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($s, FilesystemIterator::SKIP_DOTS), RecursiveIteratorIterator::CHILD_FIRST);
    foreach ($it as $f) { $f->isDir() ? @rmdir($f->getPathname()) : @unlink($f->getPathname()); }
}
echo "DONE\n";
