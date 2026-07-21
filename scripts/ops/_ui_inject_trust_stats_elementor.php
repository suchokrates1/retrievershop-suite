<?php
/**
 * Insert [rs_trust_stats] HTML widget into homepage Elementor
 * between "Co mówią o naszym sklepie?" and "Opinie klientów".
 */
require '/var/www/html/wp-load.php';
wp_set_current_user(1);

$front = (int) get_option('page_on_front');
$raw = get_post_meta($front, '_elementor_data', true);
$data = json_decode($raw, true);
if (!is_array($data)) {
    fwrite(STDERR, "bad elementor json\n");
    exit(1);
}

function rs_find_and_inject(&$els, &$changed) {
    if (!is_array($els)) {
        return false;
    }
    // Look for a column/section children list that contains both widgets
    $opinieIdx = null;
    foreach ($els as $i => $el) {
        $title = (string) ($el['settings']['title'] ?? '');
        $editor = (string) ($el['settings']['editor'] ?? '');
        $plain = wp_strip_all_tags($editor);
        if (stripos($title, 'Opinie klientów') !== false) {
            $opinieIdx = $i;
            break;
        }
        // Also detect via editor text-editor sibling structure handled below
        if (!empty($el['elements']) && rs_find_and_inject($el['elements'], $changed)) {
            return true;
        }
    }
    if ($opinieIdx === null) {
        return false;
    }
    // Already injected?
    foreach ($els as $el) {
        $html = (string) ($el['settings']['html'] ?? '');
        $editor = (string) ($el['settings']['editor'] ?? '');
        if (strpos($html . $editor, 'rs_trust_stats') !== false || strpos($html . $editor, 'rs-trust-stats') !== false) {
            echo "already_injected\n";
            return true;
        }
    }
    $widget = [
        'id' => substr(md5('rs-trust-stats-' . time()), 0, 7),
        'elType' => 'widget',
        'widgetType' => 'shortcode',
        'settings' => [
            'shortcode' => '[rs_trust_stats]',
        ],
        'elements' => [],
    ];
    array_splice($els, $opinieIdx, 0, [$widget]);
    $changed = true;
    echo "injected_before_opinie_at={$opinieIdx}\n";
    return true;
}

$changed = false;
if (!rs_find_and_inject($data, $changed)) {
    fwrite(STDERR, "opinie heading not found\n");
    exit(1);
}

if ($changed) {
    $json = wp_json_encode($data);
    // Elementor expects slashed in some WP versions
    update_post_meta($front, '_elementor_data', wp_slash($json));
    update_post_meta($front, '_elementor_css', '');
    if (class_exists('\\Elementor\\Plugin')) {
        \Elementor\Plugin::$instance->files_manager->clear_cache();
    }
    clean_post_cache($front);
    echo "elementor_saved\n";
}

delete_transient('rs_allegro_trust');
$opt = get_option('rs_allegro_trust');
if (is_array($opt)) {
    set_transient('rs_allegro_trust', $opt, 6 * HOUR_IN_SECONDS);
}

wp_cache_flush();
$root = WP_CONTENT_DIR . '/cache';
if (is_dir($root)) {
    $it = new RecursiveIteratorIterator(
        new RecursiveDirectoryIterator($root, FilesystemIterator::SKIP_DOTS),
        RecursiveIteratorIterator::CHILD_FIRST
    );
    foreach ($it as $f) {
        $f->isDir() ? @rmdir($f->getPathname()) : @unlink($f->getPathname());
    }
}
echo "DONE\n";
