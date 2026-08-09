<?php
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');
echo function_exists('rs_elementor_regenerate_home_css') ? "guard_loaded=1\n" : "guard_loaded=0\n";
$home_id = (int) get_option('page_on_front');
$p = WP_CONTENT_DIR . '/uploads/elementor/css/post-' . $home_id . '.css';
echo "home_id={$home_id}\n";
echo 'css_exists=' . (is_file($p) ? 'yes size=' . filesize($p) : 'no') . "\n";
