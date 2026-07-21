<?php
/**
 * Wyczysc AIOSEO title z sufiksem koloru na produktach variable (po merge).
 */
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
global $wpdb;

$ids = $wpdb->get_col(
    "SELECT ID FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish'"
);
$n = 0;
foreach ($ids as $pid) {
    $pid = (int) $pid;
    $p = wc_get_product($pid);
    if (!$p || $p->get_type() !== 'variable') {
        continue;
    }
    $name = $p->get_name();
    // strip emdash color from post title if present
    $clean = preg_replace('/\s+[—–-]\s+\S+\s*$/u', '', $name);
    $clean = trim($clean);
    if ($clean && $clean !== $name) {
        wp_update_post(['ID' => $pid, 'post_title' => $clean]);
        $name = $clean;
    }
    $seo_title = $name . ' | Retriever Shop';
    update_post_meta($pid, '_aioseo_title', $seo_title);
    $table = $wpdb->prefix . 'aioseo_posts';
    $wpdb->update($table, [
        'title' => $seo_title,
        'og_title' => $name,
    ], ['post_id' => $pid]);
    $n++;
    echo "#{$pid} {$seo_title}\n";
}
echo "updated={$n}\n";

$dups = $wpdb->get_results(
    "SELECT post_title, COUNT(*) c FROM {$wpdb->posts}
     WHERE post_type='product' AND post_status='publish'
     GROUP BY post_title HAVING c>1 ORDER BY c DESC LIMIT 10"
);
echo "dup_groups=" . count($dups) . "\n";
foreach ($dups as $d) {
    echo "{$d->c}x {$d->post_title}\n";
}
$pub = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish'"
);
$priv = (int) $wpdb->get_var(
    "SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type='product' AND post_status='private'"
);
echo "publish={$pub} private={$priv}\n";
