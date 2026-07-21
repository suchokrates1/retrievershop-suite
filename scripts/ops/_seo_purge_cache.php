<?php
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
wp_set_current_user(1);

if (class_exists('\\Elementor\\Plugin')) {
    \Elementor\Plugin::$instance->files_manager->clear_cache();
    echo "elementor ok\n";
}
if (function_exists('wp_cache_flush')) {
    wp_cache_flush();
    echo "wp_cache_flush ok\n";
}

// Seraphinite Accelerator
if (function_exists('seraph_accel_deleteCache')) {
    seraph_accel_deleteCache();
    echo "seraph_accel_deleteCache ok\n";
}
do_action('seraph_accel_cache_clean');
do_action('litespeed_purge_all');

// Common option / file based
$dirs = [
    WP_CONTENT_DIR . '/cache',
    WP_CONTENT_DIR . '/uploads/cache',
];
foreach ($dirs as $d) {
    if (is_dir($d)) {
        echo "cache_dir={$d}\n";
    }
}

// AIOSEO sitemap regenerate nudge
if (function_exists('aioseo')) {
    try {
        aioseo()->sitemap->regenerate();
        echo "aioseo sitemap regenerate ok\n";
    } catch (Throwable $e) {
        echo "aioseo sitemap skip: {$e->getMessage()}\n";
    }
}

echo "DONE\n";
