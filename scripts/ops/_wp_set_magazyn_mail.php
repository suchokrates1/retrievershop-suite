<?php
require '/var/www/html/wp-load.php';
wp_set_current_user(1);

$secret = trim(file_get_contents('/tmp/rs_mail_secret.txt'));
if ($secret === '') {
    echo "NO_SECRET\n";
    exit(1);
}
update_option('rs_magazyn_mail_url', 'https://magazyn.retrievershop.pl/api/shop-mail/newsletter-welcome', false);
update_option('rs_magazyn_mail_secret', $secret, false);
echo "url=" . get_option('rs_magazyn_mail_url') . "\n";
echo "secret_set=" . (get_option('rs_magazyn_mail_secret') ? '1' : '0') . " len=" . strlen((string)get_option('rs_magazyn_mail_secret')) . "\n";

// Ensure mu-plugin present
$src = '/tmp/_mu_retriever_newsletter.php';
$dst = WPMU_PLUGIN_DIR . '/retriever-newsletter.php';
if (file_exists($src)) {
    copy($src, $dst);
    echo "mu_plugin_copied\n";
}
echo "class=" . (class_exists('RS_Newsletter') ? '1' : 'need_reload') . "\n";

// Disable woo customer emails already in plugin; purge cache
$s = WP_CONTENT_DIR . '/cache/seraphinite-accelerator/s';
if (is_dir($s)) {
    $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($s, FilesystemIterator::SKIP_DOTS), RecursiveIteratorIterator::CHILD_FIRST);
    foreach ($it as $f) { $f->isDir() ? @rmdir($f->getPathname()) : @unlink($f->getPathname()); }
}
echo "DONE\n";
