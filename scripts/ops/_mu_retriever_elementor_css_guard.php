<?php
/**
 * Plugin Name: Retriever Elementor CSS Guard
 * Description: Po clear_cache Elementora od razu regeneruje CSS strony głównej i kita — zapobiega „gołej” homepage.
 */
if (!defined('ABSPATH')) {
    exit;
}

/**
 * Regenerate Elementor external CSS for front page + active kit.
 */
function rs_elementor_regenerate_home_css(): void
{
    if (!class_exists('\\Elementor\\Core\\Files\\CSS\\Post')) {
        return;
    }
    $home_id = (int) get_option('page_on_front');
    if ($home_id > 0) {
        try {
            (new \Elementor\Core\Files\CSS\Post($home_id))->update();
        } catch (Throwable $e) {
            // ignore — next front-page hit will retry
        }
    }
    $kit_id = (int) get_option('elementor_active_kit');
    if ($kit_id > 0) {
        try {
            (new \Elementor\Core\Files\CSS\Post($kit_id))->update();
        } catch (Throwable $e) {
            // ignore
        }
    }
}

// Elementor fires this after deleting generated CSS files.
add_action('elementor/core/files/clear_cache', 'rs_elementor_regenerate_home_css', 20);

// Safety net: if CSS file vanished (purge race / permissions), rebuild on front page render.
add_action('template_redirect', static function () {
    if (!is_front_page() || is_admin()) {
        return;
    }
    $home_id = (int) get_option('page_on_front');
    if ($home_id <= 0) {
        return;
    }
    $path = WP_CONTENT_DIR . '/uploads/elementor/css/post-' . $home_id . '.css';
    if (is_file($path) && filesize($path) > 100) {
        return;
    }
    rs_elementor_regenerate_home_css();
}, 1);
