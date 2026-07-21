<?php
/**
 * Po merge: w duplikatach title zostaw parenta z najwieksza liczba wariantow, reszte private.
 */
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
global $wpdb;

$dups = $wpdb->get_results(
    "SELECT post_title, COUNT(*) c FROM {$wpdb->posts}
     WHERE post_type='product' AND post_status='publish'
     GROUP BY post_title HAVING c>1"
);
$priv = 0;
foreach ($dups as $d) {
    $rows = $wpdb->get_results($wpdb->prepare(
        "SELECT ID FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish' AND post_title=%s",
        $d->post_title
    ));
    $scored = [];
    foreach ($rows as $r) {
        $p = wc_get_product((int) $r->ID);
        if (!$p) {
            continue;
        }
        $children = $p->is_type('variable') ? count($p->get_children()) : 0;
        $scored[] = ['id' => (int) $r->ID, 'children' => $children, 'slug' => $p->get_slug()];
    }
    usort($scored, fn($a, $b) => $b['children'] <=> $a['children'] ?: $b['id'] <=> $a['id']);
    if (!$scored) {
        continue;
    }
    $keep = $scored[0];
    echo "KEEP #{$keep['id']} children={$keep['children']} {$d->post_title}\n";
    foreach (array_slice($scored, 1) as $row) {
        wp_update_post(['ID' => $row['id'], 'post_status' => 'private']);
        echo "  private #{$row['id']} children={$row['children']} {$row['slug']}\n";
        $priv++;
    }
}
$left = $wpdb->get_var(
    "SELECT COUNT(*) FROM (
        SELECT post_title FROM {$wpdb->posts}
        WHERE post_type='product' AND post_status='publish'
        GROUP BY post_title HAVING COUNT(*)>1
     ) t"
);
$pub = (int) $wpdb->get_var("SELECT COUNT(*) FROM {$wpdb->posts} WHERE post_type='product' AND post_status='publish'");
echo "privatized={$priv} dup_groups_left={$left} publish={$pub}\n";
