<?php
/**
 * Plugin Name: Retriever SMTP
 * Description: Zwykłe SMTP (OVH) dla wp_mail — zastępuje Site Mailer.
 */
if (!defined('ABSPATH')) {
    exit;
}

/**
 * @return array{host:string,port:int,user:string,pass:string,from_email:string,from_name:string,encryption:string}
 */
function rs_smtp_config(): array {
    $host = (string) get_option('retriever_smtp_host', '');
    $port = (int) get_option('retriever_smtp_port', 465);
    $user = (string) get_option('retriever_smtp_user', '');
    $pass = (string) get_option('retriever_smtp_pass', '');
    $from_email = (string) get_option('retriever_smtp_from_email', $user);
    $from_name = (string) get_option('retriever_smtp_from_name', 'Retriever Shop');
    $encryption = (string) get_option('retriever_smtp_encryption', 'ssl');
    if ($encryption === '' && $port === 465) {
        $encryption = 'ssl';
    }
    if ($encryption === '' && $port === 587) {
        $encryption = 'tls';
    }
    return [
        'host' => $host,
        'port' => $port > 0 ? $port : 465,
        'user' => $user,
        'pass' => $pass,
        'from_email' => $from_email !== '' ? $from_email : $user,
        'from_name' => $from_name !== '' ? $from_name : 'Retriever Shop',
        'encryption' => strtolower($encryption),
    ];
}

function rs_smtp_is_configured(): bool {
    $c = rs_smtp_config();
    return $c['host'] !== '' && $c['user'] !== '' && $c['pass'] !== '';
}

add_filter('wp_mail_from', static function ($from) {
    if (!rs_smtp_is_configured()) {
        return $from;
    }
    return rs_smtp_config()['from_email'];
}, 20);

add_filter('wp_mail_from_name', static function ($name) {
    if (!rs_smtp_is_configured()) {
        return $name;
    }
    return rs_smtp_config()['from_name'];
}, 20);

add_action('phpmailer_init', static function ($phpmailer) {
    if (!rs_smtp_is_configured()) {
        return;
    }
    $c = rs_smtp_config();
    $phpmailer->isSMTP();
    $phpmailer->Host = $c['host'];
    $phpmailer->Port = $c['port'];
    $phpmailer->SMTPAuth = true;
    $phpmailer->Username = $c['user'];
    $phpmailer->Password = $c['pass'];
    if ($c['encryption'] === 'ssl') {
        $phpmailer->SMTPSecure = 'ssl';
        $phpmailer->SMTPAutoTLS = false;
    } elseif ($c['encryption'] === 'tls') {
        $phpmailer->SMTPSecure = 'tls';
        $phpmailer->SMTPAutoTLS = true;
    } else {
        $phpmailer->SMTPSecure = '';
        $phpmailer->SMTPAutoTLS = false;
    }
    $phpmailer->From = $c['from_email'];
    $phpmailer->FromName = $c['from_name'];
    $phpmailer->Sender = $c['from_email'];
    $phpmailer->CharSet = 'UTF-8';
}, 5);
