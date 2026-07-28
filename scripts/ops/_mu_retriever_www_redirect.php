<?php
/**
 * Canonical host: redirect www → apex (non-www).
 */
add_action('template_redirect', function () {
    if (is_admin() || wp_doing_ajax() || wp_doing_cron()) {
        return;
    }
    $host = $_SERVER['HTTP_HOST'] ?? '';
    if ($host === '' || strcasecmp($host, 'www.retrievershop.pl') !== 0) {
        return;
    }
    $uri = $_SERVER['REQUEST_URI'] ?? '/';
    wp_redirect('https://retrievershop.pl' . $uri, 301);
    exit;
}, 0);
