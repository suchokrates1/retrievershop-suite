<?php
/**
 * Publish canonical Woo IDs from magazyn; private other publish products with same title.
 * Input: /tmp/rs_canonical_woo_ids.json {"canonical_ids":[...]}
 */
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');

$path = $argv[1] ?? '/tmp/rs_canonical_woo_ids.json';
$data = json_decode(file_get_contents($path), true);
$canon = array_map('intval', $data['canonical_ids'] ?? []);
$canon_set = array_fill_keys($canon, true);
echo 'canonical_count=' . count($canon) . "\n";

foreach ($canon as $id) {
    $p = get_post($id);
    if (!$p || $p->post_type !== 'product') {
        echo "missing #{$id}\n";
        continue;
    }
    if ($p->post_status !== 'publish') {
        wp_update_post(['ID' => $id, 'post_status' => 'publish']);
        echo "publish #{$id}\n";
    }
}

// Private non-canonical with same title as any canonical
$priv = 0;
foreach ($canon as $id) {
    $title = get_the_title($id);
    if (!$title) {
        continue;
    }
    $q = new WP_Query([
        'post_type' => 'product',
        'post_status' => 'publish',
        'posts_per_page' => -1,
        'title' => $title,
        'fields' => 'ids',
    ]);
    // WP_Query title is exact in newer WP; fallback SQL
}
global $wpdb;
foreach ($canon as $id) {
    $title = get_the_title($id);
    $rows = $wpdb->get_col($wpdb->prepare(
        "SELECT ID FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish' AND post_title=%s AND ID<>%d",
        $title,
        $id
    ));
    foreach ($rows as $oid) {
        $oid = (int) $oid;
        if (isset($canon_set[$oid])) {
            continue;
        }
        wp_update_post(['ID' => $oid, 'post_status' => 'private']);
        echo "private #{$oid} (dup of #{$id})\n";
        $priv++;
    }
}

$dups = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM (
        SELECT post_title FROM {$wpdb->posts}
        WHERE post_type='product' AND post_status='publish'
        GROUP BY post_title HAVING COUNT(*)>1
     ) t"
);
$pub = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish'");
echo "privatized={$priv} dup_groups={$dups} publish={$pub}\n";
