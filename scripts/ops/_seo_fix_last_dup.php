<?php
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
// Ostatnia para z tym samym tytułem — rozróżnij po slugu (XL / duży)
$fixes = [
    3562 => 'Szelki dla psa Truelove Front Line — pomarańczowe XL',
];
foreach ($fixes as $id => $title) {
    wp_update_post(['ID' => $id, 'post_title' => $title]);
    update_post_meta($id, '_aioseo_title', $title . ' | Retriever Shop');
    echo "fixed #{$id} -> {$title}\n";
}
$left = $GLOBALS['wpdb']->get_var(
    "SELECT COUNT(*) FROM (
        SELECT post_title FROM {$GLOBALS['wpdb']->posts}
        WHERE post_type='product' AND post_status='publish'
        GROUP BY post_title HAVING COUNT(*)>1
     ) t"
);
echo "dup_groups_left={$left}\n";
