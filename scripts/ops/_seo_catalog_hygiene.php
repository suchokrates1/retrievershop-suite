<?php
/**
 * Literówki w produktach + 301, scalenie kategorii pasów, opisy kategorii.
 */
require '/var/www/html/wp-load.php';

header('Content-Type: text/plain; charset=utf-8');

function rs_ensure_redirect($from_path, $to_url) {
    // Prefer Redirection plugin if present; else store as post meta note.
    // Use Yoast/AIOSEO-compatible: insert into wp_redirection_items if table exists.
    global $wpdb;
    $table = $wpdb->prefix . 'redirection_items';
    $exists = $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table));
    if ($exists !== $table) {
        echo "NO redirection plugin — slug change alone (WP may 301 old slug briefly)\n";
        return;
    }
    $from = '/' . ltrim($from_path, '/');
    $existing = $wpdb->get_var($wpdb->prepare(
        "SELECT id FROM {$table} WHERE url = %s LIMIT 1",
        $from
    ));
    if ($existing) {
        $wpdb->update($table, [
            'action_data' => $to_url,
            'action_type' => 'url',
            'action_code' => 301,
            'match_type' => 'url',
            'status' => 'enabled',
        ], ['id' => $existing]);
        return;
    }
    $wpdb->insert($table, [
        'url' => $from,
        'match_url' => $from,
        'match_type' => 'url',
        'action_type' => 'url',
        'action_code' => 301,
        'action_data' => $to_url,
        'group_id' => 1,
        'status' => 'enabled',
        'regex' => 0,
    ]);
}

// --- Typo product renames ---
$typo_map = [
    2583 => [
        'title' => 'Szelki dla psa Truelove Front Line Premium',
        'slug' => 'szelki-dla-psa-truelove-front-line-premium-czarne',
    ],
    2989 => [
        'title' => 'Szelki dla psa Truelove Front Line Premium',
        'slug' => 'szelki-dla-psa-truelove-front-line-premium-czerwone',
    ],
    2624 => [
        'title' => 'Szelki dla psa Truelove Front Line Premium',
        'slug' => 'szelki-dla-psa-truelove-front-line-premium-granatowe',
    ],
];

foreach ($typo_map as $id => $fix) {
    $post = get_post($id);
    if (!$post || $post->post_type !== 'product') {
        echo "skip missing #{$id}\n";
        continue;
    }
    $old_slug = $post->post_name;
    $old_url = get_permalink($id);
    wp_update_post([
        'ID' => $id,
        'post_title' => $fix['title'],
        'post_name' => $fix['slug'],
    ]);
    clean_post_cache($id);
    $new_url = get_permalink($id);
    if ($old_slug && $old_slug !== $fix['slug']) {
        rs_ensure_redirect($old_slug, $new_url);
        // Also product permalink path
        rs_ensure_redirect('produkt/' . $old_slug . '/', $new_url);
    }
    echo "fixed #{$id} {$old_slug} -> {$fix['slug']} title={$fix['title']}\n";
}

// Broad typo search/replace in titles
global $wpdb;
$replacements = [
    'Trelove' => 'Truelove',
    'Truelve' => 'Truelove',
    'Fronr' => 'Front',
    'ptemium' => 'Premium',
    'Ptemium' => 'Premium',
    'średnieho' => 'średniego',
    'czerwonw' => 'czerwone',
];
foreach ($replacements as $bad => $good) {
    $rows = $wpdb->get_results($wpdb->prepare(
        "SELECT ID, post_title, post_name FROM {$wpdb->posts}
         WHERE post_type='product' AND post_status IN ('publish','private','draft')
         AND (post_title LIKE %s OR post_name LIKE %s)",
        '%' . $wpdb->esc_like($bad) . '%',
        '%' . $wpdb->esc_like(sanitize_title($bad)) . '%'
    ));
    foreach ($rows as $row) {
        $title = str_replace($bad, $good, $row->post_title);
        $slug = $row->post_name;
        $slug_bad = sanitize_title($bad);
        $slug_good = sanitize_title($good);
        if ($slug_bad && str_contains($slug, $slug_bad)) {
            $slug = str_replace($slug_bad, $slug_good, $slug);
        }
        if ($title === $row->post_title && $slug === $row->post_name) {
            continue;
        }
        $old_slug = $row->post_name;
        wp_update_post(['ID' => (int) $row->ID, 'post_title' => $title, 'post_name' => $slug]);
        if ($old_slug !== $slug) {
            rs_ensure_redirect('produkt/' . $old_slug . '/', get_permalink((int) $row->ID));
        }
        echo "typo #{$row->ID}: {$row->post_title} -> {$title}\n";
    }
}

// --- Merge categories: Pas samochodowy -> Pasy bezpieczeństwa ---
$target = get_term_by('slug', 'pasy-bezpieczenstwa', 'product_cat');
$source = get_term_by('slug', 'pas-samochodowy', 'product_cat');
if (!$target) {
    $created = wp_insert_term('Pasy bezpieczeństwa', 'product_cat', ['slug' => 'pasy-bezpieczenstwa']);
    if (!is_wp_error($created)) {
        $target = get_term((int) $created['term_id'], 'product_cat');
        echo "created target category\n";
    }
}
if ($target && $source) {
    $products = get_posts([
        'post_type' => 'product',
        'posts_per_page' => -1,
        'fields' => 'ids',
        'tax_query' => [[
            'taxonomy' => 'product_cat',
            'field' => 'term_id',
            'terms' => [(int) $source->term_id],
        ]],
    ]);
    foreach ($products as $pid) {
        wp_set_object_terms((int) $pid, [(int) $target->term_id], 'product_cat', true);
        wp_remove_object_terms((int) $pid, [(int) $source->term_id], 'product_cat');
        echo "moved product #{$pid} to Pasy bezpieczeństwa\n";
    }
    wp_delete_term((int) $source->term_id, 'product_cat');
    echo "deleted category pas-samochodowy\n";
} else {
    echo "category merge skip target=" . ($target ? 'yes' : 'no') . " source=" . ($source ? 'yes' : 'no') . "\n";
}

// Category descriptions
$cat_descriptions = [
    'szelki' => 'Szelki dla psa Truelove — modele spacerowe, treningowe i Cordura. Wybierz rozmiar i kolor dopasowany do Twojego psa.',
    'smycze' => 'Smycze dla psa Truelove: klasyczne, z amortyzatorem i trekkingowe. Solidne materiały i wygodne uchwyty.',
    'obroza' => 'Obroże dla psa Truelove — treningowe, odblaskowe i materiałowe. Bezpieczne dopasowanie na co dzień.',
    'saszetki' => 'Saszetki i akcesoria na przysmaki Truelove — praktyczne na spacer i trening.',
    'pasy-bezpieczenstwa' => 'Pasy bezpieczeństwa / samochodowe dla psa Truelove — bezpieczny przewóz w aucie.',
];
foreach ($cat_descriptions as $slug => $desc) {
    $term = get_term_by('slug', $slug, 'product_cat');
    if (!$term || is_wp_error($term)) {
        echo "cat missing {$slug}\n";
        continue;
    }
    wp_update_term((int) $term->term_id, 'product_cat', ['description' => $desc]);
    echo "cat desc {$slug}\n";
}

echo "DONE catalog hygiene\n";
