<?php
/**
 * Fill empty product descriptions by copying from a sibling with content
 * (same title prefix / brand series) when Allegro offers are gone (404).
 */
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');

$empty = get_posts([
    'post_type' => 'product',
    'post_status' => 'publish',
    'posts_per_page' => -1,
    'fields' => 'ids',
]);
$filled = 0;
foreach ($empty as $id) {
    $p = wc_get_product($id);
    if (!$p) {
        continue;
    }
    $desc = trim($p->get_description());
    if ($desc !== '') {
        continue;
    }
    $name = $p->get_name();
    // Find sibling with longest shared prefix and non-empty desc
    $candidates = get_posts([
        'post_type' => 'product',
        'post_status' => 'publish',
        'posts_per_page' => 30,
        's' => implode(' ', array_slice(explode(' ', $name), 0, 5)),
        'post__not_in' => [$id],
    ]);
    $best = null;
    $best_score = 0;
    foreach ($candidates as $c) {
        $cp = wc_get_product($c->ID);
        if (!$cp) {
            continue;
        }
        $cd = trim($cp->get_description());
        if (strlen($cd) < 200) {
            continue;
        }
        similar_text(mb_strtolower($name), mb_strtolower($cp->get_name()), $pct);
        if ($pct > $best_score) {
            $best_score = $pct;
            $best = $cp;
        }
    }
    if (!$best || $best_score < 40) {
        echo "no donor for #{$id} {$name}\n";
        continue;
    }
    $p->set_description($best->get_description());
    if (!trim($p->get_short_description())) {
        $p->set_short_description($best->get_short_description());
    }
    // Copy featured image if missing
    if (!get_post_thumbnail_id($id) && ($thumb = get_post_thumbnail_id($best->get_id()))) {
        set_post_thumbnail($id, $thumb);
    }
    $p->save();
    $filled++;
    echo "filled #{$id} from #{$best->get_id()} score={$best_score} name={$name}\n";
}
echo "filled={$filled}\n";
