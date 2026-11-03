<?php
/**
 * Configure Retriever SMTP options, deactivate Site Mailer, send probe mail.
 * Env: SMTP_SERVER, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, EMAIL_FROM_NAME, TEST_TO
 */
require_once '/var/www/html/wp-load.php';

$host = getenv('SMTP_SERVER') ?: '';
$port = (int) (getenv('SMTP_PORT') ?: 465);
$user = getenv('SMTP_USERNAME') ?: '';
$pass = getenv('SMTP_PASSWORD') ?: '';
$from_name = getenv('EMAIL_FROM_NAME') ?: 'Retriever Shop';
$test_to = getenv('TEST_TO') ?: 'dawsuchodolski@gmail.com';

if ($host === '' || $user === '' || $pass === '') {
    fwrite(STDERR, "Missing SMTP env\n");
    exit(1);
}

update_option('retriever_smtp_host', $host, false);
update_option('retriever_smtp_port', $port, false);
update_option('retriever_smtp_user', $user, false);
update_option('retriever_smtp_pass', $pass, false);
update_option('retriever_smtp_from_email', $user, false);
update_option('retriever_smtp_from_name', $from_name, false);
update_option('retriever_smtp_encryption', $port === 465 ? 'ssl' : 'tls', false);

echo "SMTP options saved host=$host port=$port user=$user from_name=$from_name\n";
echo "smtp_configured=" . (function_exists('rs_smtp_is_configured') && rs_smtp_is_configured() ? 'yes' : 'no') . "\n";

// Deactivate Site Mailer if active
if (!function_exists('deactivate_plugins')) {
    require_once ABSPATH . 'wp-admin/includes/plugin.php';
}
if (is_plugin_active('site-mailer/site-mailer.php')) {
    deactivate_plugins('site-mailer/site-mailer.php', true);
    echo "site-mailer deactivated\n";
} else {
    echo "site-mailer already inactive\n";
}

// Ensure Site Mailer won't steal mail if somehow loaded
if (has_filter('pre_wp_mail')) {
    echo "WARNING: pre_wp_mail still has filters\n";
} else {
    echo "pre_wp_mail clear\n";
}

$mail_error = null;
add_action('wp_mail_failed', static function ($e) use (&$mail_error) {
    $mail_error = $e->get_error_message();
}, 10, 1);

add_action('phpmailer_init', static function ($phpmailer) {
    echo 'phpmailer mailer=' . $phpmailer->Mailer
        . ' host=' . $phpmailer->Host
        . ' port=' . $phpmailer->Port
        . ' secure=' . $phpmailer->SMTPSecure
        . ' user=' . $phpmailer->Username
        . "\n";
}, 99);

$subject = '[RetrieverShop] Test SMTP ' . gmdate('Y-m-d H:i:s') . ' UTC';
$body = "Test zwykłego SMTP (OVH) po wyłączeniu Site Mailer.\n"
    . "Jeśli to czytasz — wp_mail działa.\n"
    . 'Host: ' . $host . ':' . $port . "\n"
    . 'From: ' . $user . "\n";

$sent = wp_mail($test_to, $subject, $body, ['Content-Type: text/plain; charset=UTF-8']);
echo 'wp_mail_to=' . $test_to . "\n";
echo 'wp_mail_sent=' . var_export($sent, true) . "\n";
echo 'wp_mail_error=' . var_export($mail_error, true) . "\n";

if (!$sent) {
    exit(2);
}
