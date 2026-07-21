<?php
/**
 * Merge JSON redirect map into option rs_seo_slug_redirects.
 * Usage: docker exec retrievershop-wp php /tmp/_seo_apply_redirects.php /tmp/redirects.json
 */
require '/var/www/html/wp-load.php';
header('Content-Type: text/plain; charset=utf-8');

$path = $argv[1] ?? '/tmp/rs_seo_redirects.json';
if (!is_readable($path)) {
    echo "missing {$path}\n";
    exit(1);
}
$raw = file_get_contents($path);
$data = json_decode($raw, true);
if (!is_array($data)) {
    echo "invalid json\n";
    exit(1);
}
$existing = get_option('rs_seo_slug_redirects', []);
if (is_string($existing)) {
    $existing = json_decode($existing, true) ?: [];
}
if (!is_array($existing)) {
    $existing = [];
}
$merged = array_merge($existing, $data);
update_option('rs_seo_slug_redirects', $merged, false);
echo 'redirects_total=' . count($merged) . "\n";
foreach ($data as $from => $to) {
    echo "{$from} -> {$to}\n";
}
