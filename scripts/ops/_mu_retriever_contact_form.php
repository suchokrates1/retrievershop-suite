<?php
/**
 * Plugin Name: Retriever Contact Form
 * Description: [rs_contact_form] — formularz Kontakt → e-mail + link Messenger, antybot.
 */
if (!defined('ABSPATH')) {
    exit;
}

const RS_CONTACT_TO = 'kontakt@retrievershop.pl';
const RS_CONTACT_MESSENGER = 'https://m.me/retrievershop';

function rs_contact_client_ip(): string {
    $ip = $_SERVER['REMOTE_ADDR'] ?? '';
    return is_string($ip) ? substr($ip, 0, 64) : '';
}

function rs_contact_make_challenge(): array {
    $a = random_int(2, 9);
    $b = random_int(1, 8);
    $sum = $a + $b;
    $token = wp_generate_password(20, false, false);
    set_transient('rs_cf_' . $token, [
        'sum' => $sum,
        't' => time(),
        'ip' => rs_contact_client_ip(),
    ], 30 * MINUTE_IN_SECONDS);
    return [
        'token' => $token,
        'question' => sprintf('Ile to jest %d + %d?', $a, $b),
    ];
}

function rs_contact_rate_limited(): bool {
    $key = 'rs_cf_rl_' . md5(rs_contact_client_ip());
    $n = (int) get_transient($key);
    if ($n >= 5) {
        return true;
    }
    set_transient($key, $n + 1, HOUR_IN_SECONDS);
    return false;
}

add_action('init', static function () {
    register_post_type('rs_contact_msg', [
        'labels' => [
            'name' => 'Wiadomości z formularza',
            'singular_name' => 'Wiadomość',
        ],
        'public' => false,
        'show_ui' => true,
        'show_in_menu' => 'edit.php?post_type=page',
        'supports' => ['title', 'editor'],
        'capability_type' => 'post',
        'map_meta_cap' => true,
    ]);
});

add_shortcode('rs_contact_form', static function () {
    $chal = rs_contact_make_challenge();
    $action = esc_url(admin_url('admin-post.php'));
    ob_start();
    ?>
<div class="rs-cf" id="rs-contact-form">
  <form class="rs-cf__form" method="post" action="<?php echo $action; ?>" novalidate>
    <input type="hidden" name="action" value="rs_contact_submit">
    <input type="hidden" name="rs_cf_token" value="<?php echo esc_attr($chal['token']); ?>">
    <?php wp_nonce_field('rs_contact_submit', 'rs_cf_nonce'); ?>
    <input type="hidden" name="rs_cf_started" value="<?php echo esc_attr((string) time()); ?>">

    <!-- honeypot -->
    <div class="rs-cf__hp" aria-hidden="true">
      <label>Strona WWW<input type="text" name="rs_cf_website" tabindex="-1" autocomplete="off"></label>
    </div>

    <div class="rs-cf__row">
      <label class="rs-cf__label" for="rs_cf_name">Imię i nazwisko</label>
      <input class="rs-cf__input" id="rs_cf_name" name="rs_cf_name" type="text" required maxlength="120" autocomplete="name">
    </div>
    <div class="rs-cf__row">
      <label class="rs-cf__label" for="rs_cf_email">E-mail</label>
      <input class="rs-cf__input" id="rs_cf_email" name="rs_cf_email" type="email" required maxlength="160" autocomplete="email">
    </div>
    <div class="rs-cf__row">
      <label class="rs-cf__label" for="rs_cf_phone">Telefon <span class="rs-cf__opt">(opcjonalnie)</span></label>
      <input class="rs-cf__input" id="rs_cf_phone" name="rs_cf_phone" type="tel" maxlength="40" autocomplete="tel">
    </div>
    <div class="rs-cf__row">
      <label class="rs-cf__label" for="rs_cf_topic">Temat</label>
      <select class="rs-cf__input" id="rs_cf_topic" name="rs_cf_topic" required>
        <option value="pytanie">Pytanie o produkt</option>
        <option value="opinia">Opinia</option>
        <option value="reklamacja">Reklamacja</option>
        <option value="zwrot">Zwrot</option>
        <option value="inne">Inne</option>
      </select>
    </div>
    <div class="rs-cf__row">
      <label class="rs-cf__label" for="rs_cf_message">Wiadomość</label>
      <textarea class="rs-cf__input rs-cf__textarea" id="rs_cf_message" name="rs_cf_message" required maxlength="4000" rows="5"></textarea>
    </div>
    <div class="rs-cf__row">
      <label class="rs-cf__label" for="rs_cf_captcha"><?php echo esc_html($chal['question']); ?></label>
      <input class="rs-cf__input" id="rs_cf_captcha" name="rs_cf_captcha" type="text" inputmode="numeric" required autocomplete="off">
    </div>

    <button class="rs-cf__submit" type="submit">Wyślij wiadomość</button>
  </form>

  <div class="rs-cf__messenger">
    <p class="rs-cf__messenger-label">Albo napisz od razu na Messengerze:</p>
    <a class="rs-cf__messenger-btn" href="<?php echo esc_url(RS_CONTACT_MESSENGER); ?>" target="_blank" rel="noopener noreferrer">
      Otwórz Messengera
    </a>
  </div>
</div>
    <?php
    return (string) ob_get_clean();
});

add_action('wp_head', static function () {
    if (is_admin()) {
        return;
    }
    if (!is_page('kontakt') && !is_page(1361)) {
        // still load CSS if shortcode present elsewhere — cheap enough on kontakt mainly
        if (!is_singular()) {
            return;
        }
    }
    echo '<style id="rs-contact-form-css">
.rs-cf{margin-top:8px;max-width:520px}
.rs-cf__form{display:grid;gap:14px}
.rs-cf__row{display:grid;gap:6px;text-align:left}
.rs-cf__label{font-size:13px;font-weight:600;color:var(--rs-ink,#1A3333);font-family:Poppins,sans-serif}
.rs-cf__opt{font-weight:500;color:var(--rs-muted,#5A6B6B)}
.rs-cf__input,.rs-cf__textarea{
  width:100%;box-sizing:border-box;min-height:46px;padding:10px 12px;
  border:1px solid rgba(23,56,62,.18);border-radius:10px;background:#fff;
  color:var(--rs-ink,#1A3333);font-size:15px;font-family:inherit;
}
.rs-cf__textarea{min-height:120px;resize:vertical}
.rs-cf__input:focus,.rs-cf__textarea:focus{outline:2px solid rgba(196,92,62,.35);border-color:var(--rs-accent,#C45C3E)}
.rs-cf__submit{
  appearance:none;border:0;border-radius:10px;min-height:48px;padding:0 18px;
  background:var(--rs-accent,#C45C3E);color:#FFFCFA;font-weight:600;font-family:Poppins,sans-serif;
  font-size:14px;cursor:pointer;transition:background .18s ease, transform .18s ease;
}
.rs-cf__submit:hover{background:var(--rs-accent-deep,#9E4A32);transform:translateY(-1px)}
.rs-cf__hp{position:absolute!important;left:-9999px!important;height:0!important;overflow:hidden!important}
.rs-cf__messenger{margin-top:22px;padding-top:18px;border-top:1px solid rgba(23,56,62,.10);text-align:left}
.rs-cf__messenger-label{margin:0 0 10px;font-size:14px;color:var(--rs-muted,#5A6B6B)}
.rs-cf__messenger-btn{
  display:inline-flex;align-items:center;justify-content:center;min-height:44px;padding:0 16px;
  border-radius:10px;border:1px solid rgba(23,56,62,.18);color:var(--rs-forest,#17383E)!important;
  text-decoration:none!important;font-weight:600;font-size:13px;font-family:Poppins,sans-serif;
  background:#fff;transition:border-color .18s ease, background .18s ease;
}
.rs-cf__messenger-btn:hover{border-color:var(--rs-forest,#17383E);background:rgba(23,56,62,.04)}
.rs-cf__notice{margin:0 0 14px;padding:12px 14px;border-radius:10px;font-size:14px;line-height:1.45}
.rs-cf__notice--ok{background:rgba(23,56,62,.06);color:var(--rs-forest,#17383E);border:1px solid rgba(23,56,62,.12)}
.rs-cf__notice--err{background:rgba(196,92,62,.08);color:#7a3422;border:1px solid rgba(196,92,62,.22)}
</style>';
}, 45);

/** Prepend flash notice when rendering shortcode after redirect. */
add_filter('do_shortcode_tag', static function ($output, $tag) {
    if ($tag !== 'rs_contact_form' || !isset($_GET['rs_cf'])) {
        return $output;
    }
    $status = sanitize_key((string) $_GET['rs_cf']);
    $map = [
        'ok' => ['ok', 'Dziękujemy! Wiadomość została wysłana. Odpowiemy najszybciej jak się da.'],
        'bot' => ['err', 'Wykryto automatyczne wypełnienie. Spróbuj ponownie.'],
        'captcha' => ['err', 'Błędna odpowiedź antybotowa. Spróbuj ponownie.'],
        'valid' => ['err', 'Uzupełnij poprawnie wszystkie wymagane pola.'],
        'rate' => ['err', 'Za dużo prób z tego adresu. Spróbuj za godzinę lub napisz na Messengera.'],
        'mail' => ['err', 'Nie udało się wysłać wiadomości. Napisz proszę na kontakt@retrievershop.pl lub Messengera.'],
        'fast' => ['err', 'Formularz wysłano zbyt szybko. Spróbuj ponownie.'],
    ];
    if (!isset($map[$status])) {
        return $output;
    }
    [$cls, $msg] = $map[$status];
    $notice = '<div class="rs-cf__notice rs-cf__notice--' . esc_attr($cls) . '" role="status">' . esc_html($msg) . '</div>';
    return $notice . $output;
}, 10, 2);

add_action('admin_post_nopriv_rs_contact_submit', 'rs_contact_handle_submit');
add_action('admin_post_rs_contact_submit', 'rs_contact_handle_submit');

function rs_contact_redirect(string $status): void {
    $url = wp_get_referer() ?: home_url('/kontakt/');
    $url = remove_query_arg('rs_cf', $url);
    $url = add_query_arg('rs_cf', $status, $url);
    if (strpos($url, '#') === false) {
        $url .= '#rs-contact-form';
    }
    wp_safe_redirect($url);
    exit;
}

function rs_contact_handle_submit(): void {
    if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
        rs_contact_redirect('valid');
    }
    if (!isset($_POST['rs_cf_nonce']) || !wp_verify_nonce((string) $_POST['rs_cf_nonce'], 'rs_contact_submit')) {
        rs_contact_redirect('bot');
    }
    // honeypot
    if (!empty($_POST['rs_cf_website'])) {
        rs_contact_redirect('bot');
    }
    $started = (int) ($_POST['rs_cf_started'] ?? 0);
    if ($started <= 0 || (time() - $started) < 3) {
        rs_contact_redirect('fast');
    }

    $token = sanitize_text_field((string) ($_POST['rs_cf_token'] ?? ''));
    $chal = $token !== '' ? get_transient('rs_cf_' . $token) : false;
    delete_transient('rs_cf_' . $token);
    $answer = trim((string) ($_POST['rs_cf_captcha'] ?? ''));
    if (!is_array($chal) || !isset($chal['sum']) || (string) (int) $answer !== (string) (int) $chal['sum']) {
        rs_contact_redirect('captcha');
    }
    if (rs_contact_rate_limited()) {
        rs_contact_redirect('rate');
    }

    $name = sanitize_text_field((string) ($_POST['rs_cf_name'] ?? ''));
    $email = sanitize_email((string) ($_POST['rs_cf_email'] ?? ''));
    $phone = sanitize_text_field((string) ($_POST['rs_cf_phone'] ?? ''));
    $topic = sanitize_key((string) ($_POST['rs_cf_topic'] ?? 'inne'));
    $message = sanitize_textarea_field((string) ($_POST['rs_cf_message'] ?? ''));

    if ($name === '' || $email === '' || !is_email($email) || $message === '') {
        rs_contact_redirect('valid');
    }

    $topics = [
        'pytanie' => 'Pytanie o produkt',
        'opinia' => 'Opinia',
        'reklamacja' => 'Reklamacja',
        'zwrot' => 'Zwrot',
        'inne' => 'Inne',
    ];
    $topic_label = $topics[$topic] ?? 'Inne';

    $body = "Nowa wiadomość z formularza Kontakt\n\n"
        . "Imię: {$name}\n"
        . "E-mail: {$email}\n"
        . "Telefon: " . ($phone !== '' ? $phone : '—') . "\n"
        . "Temat: {$topic_label}\n\n"
        . "Wiadomość:\n{$message}\n\n"
        . "—\nIP: " . rs_contact_client_ip() . "\n"
        . "Strona: " . home_url('/kontakt/') . "\n"
        . "Messenger: " . RS_CONTACT_MESSENGER . "\n";

    // Archive in WP (backup if mail fails / for history)
    $post_id = wp_insert_post([
        'post_type' => 'rs_contact_msg',
        'post_status' => 'private',
        'post_title' => sprintf('[%s] %s', $topic_label, $name),
        'post_content' => $body,
    ], true);
    if (!is_wp_error($post_id) && $post_id) {
        update_post_meta($post_id, '_rs_cf_email', $email);
        update_post_meta($post_id, '_rs_cf_topic', $topic);
    }

    $subject = sprintf('[Retriever Shop] %s — %s', $topic_label, $name);
    $sent = rs_contact_send_via_magazyn([
        'to_email' => RS_CONTACT_TO,
        'name' => $name,
        'email' => $email,
        'phone' => $phone,
        'topic' => $topic_label,
        'message' => $message,
        'subject' => $subject,
        'source_ip' => rs_contact_client_ip(),
        'page_url' => home_url('/kontakt/'),
    ]);

    rs_contact_redirect($sent ? 'ok' : 'mail');
}

/**
 * Wysyłka przez magazyn (SMTP OVH) — ten sam secret co newsletter.
 */
function rs_contact_send_via_magazyn(array $fields): bool {
    $nl_url = (string) get_option('rs_magazyn_mail_url', 'https://magazyn.retrievershop.pl/api/shop-mail/newsletter-welcome');
    $url = (string) get_option('rs_magazyn_contact_mail_url', '');
    if ($url === '') {
        $url = preg_replace('#/newsletter-welcome/?$#', '/contact', $nl_url) ?: '';
    }
    if ($url === '') {
        $url = 'https://magazyn.retrievershop.pl/api/shop-mail/contact';
    }
    $secret = (string) get_option('rs_magazyn_mail_secret', '');
    if ($secret === '') {
        error_log('RS_Contact: brak rs_magazyn_mail_secret');
        return false;
    }

    $payload = wp_json_encode($fields);
    if (!is_string($payload)) {
        return false;
    }

    $sig = hash_hmac('sha256', $payload, $secret);
    $response = wp_remote_post($url, [
        'timeout' => 20,
        'headers' => [
            'Content-Type' => 'application/json',
            'Authorization' => 'Bearer ' . $secret,
            'X-RS-Mail-Signature' => $sig,
        ],
        'body' => $payload,
    ]);
    if (is_wp_error($response)) {
        error_log('RS_Contact: ' . $response->get_error_message());
        return false;
    }
    $code = (int) wp_remote_retrieve_response_code($response);
    if ($code < 200 || $code >= 300) {
        error_log('RS_Contact: HTTP ' . $code . ' ' . wp_remote_retrieve_body($response));
        return false;
    }
    return true;
}
