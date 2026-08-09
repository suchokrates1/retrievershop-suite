<?php
// Simulate early MU block path without full WP.
$_SERVER['HTTP_USER_AGENT'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36 (compatible; meta-externalagent/1.1 (+https://developers.facebook.com/docs/sharing/webmasters/crawler))';
$_SERVER['REQUEST_URI'] = '/kategoria-produktu/linka/?a&b&c';
require '/var/www/html/wp-content/mu-plugins/retriever-bot-shield.php';
// Trigger hooks manually
do_action('muplugins_loaded');
echo "REACHED_END\n";
