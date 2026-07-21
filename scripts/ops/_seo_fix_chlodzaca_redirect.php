<?php
require '/var/www/html/wp-load.php';
$extra = [
    'produkt/kamizelka-dla-psa-truelove-chodzaca' => '/produkt/kamizelka-dla-psa-truelove-chlodzaca/',
];
$existing = get_option('rs_seo_slug_redirects', []);
if (is_string($existing)) {
    $existing = json_decode($existing, true) ?: [];
}
if (!is_array($existing)) {
    $existing = [];
}
// Fix bad target for chodzaca if present
foreach ($existing as $from => $to) {
    if (str_contains((string) $to, 'chodzaca')) {
        $existing[$from] = '/produkt/kamizelka-dla-psa-truelove-chlodzaca/';
    }
}
$merged = array_merge($existing, $extra);
update_option('rs_seo_slug_redirects', $merged, false);
echo 'redirects_total=' . count($merged) . "\n";
