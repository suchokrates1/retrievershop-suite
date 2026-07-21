<?php
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
global $wpdb;
$dups = $wpdb->get_results(
    "SELECT post_title, COUNT(*) c FROM {$wpdb->posts}
     WHERE post_type='product' AND post_status='publish'
     GROUP BY post_title HAVING c>1 ORDER BY c DESC LIMIT 10"
);
foreach ($dups as $d) {
    echo "{$d->c}x {$d->post_title}\n";
    $rows = $wpdb->get_results($wpdb->prepare(
        "SELECT ID, post_name FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish' AND post_title=%s",
        $d->post_title
    ));
    foreach ($rows as $r) {
        echo "  #{$r->ID} {$r->post_name}\n";
    }
}
echo 'mu_seo=' . (file_exists(WP_CONTENT_DIR . '/mu-plugins/retriever-seo.php') ? 'yes' : 'no') . "\n";
