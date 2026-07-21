<?php
/**
 * Plugin Name: Retriever Shop Newsletter
 * Description: Formularz newslettera (imię, nazwisko, e-mail) + jednorazowy kupon Woo 10%.
 */

if (!defined('ABSPATH')) {
    exit;
}

final class RS_Newsletter {
    const SHORTCODE = 'rs_newsletter_form';
    const ACTION = 'rs_newsletter_subscribe';
    const TABLE = 'rs_newsletter_subscribers';
    const DISCOUNT_PERCENT = 10;
    const COUPON_PREFIX = 'RS10-';
    const COUPON_DAYS = 30;

    public static function init(): void {
        add_action('init', [__CLASS__, 'maybe_create_table']);
        add_shortcode(self::SHORTCODE, [__CLASS__, 'render_form']);
        // Compatibility alias for old MailPoet shortcode on homepage
        add_shortcode('mailpoet_form', [__CLASS__, 'render_mailpoet_alias']);
        add_action('wp_ajax_' . self::ACTION, [__CLASS__, 'handle_ajax']);
        add_action('wp_ajax_nopriv_' . self::ACTION, [__CLASS__, 'handle_ajax']);
        add_action('wp_enqueue_scripts', [__CLASS__, 'enqueue']);
        // Maile do klienta (potwierdzenie/wysyłka) lecą z magazynu — wyłącz duplikaty Woo.
        add_filter('woocommerce_email_enabled_customer_processing_order', '__return_false');
        add_filter('woocommerce_email_enabled_customer_completed_order', '__return_false');
        add_filter('woocommerce_email_enabled_customer_on_hold_order', '__return_false');
        add_filter('woocommerce_email_enabled_customer_refunded_order', '__return_false');
    }

    public static function table_name(): string {
        global $wpdb;
        return $wpdb->prefix . self::TABLE;
    }

    public static function maybe_create_table(): void {
        global $wpdb;
        $table = self::table_name();
        // phpcs:ignore WordPress.DB.DirectDatabaseQuery
        $exists = $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table));
        if ($exists === $table) {
            return;
        }
        require_once ABSPATH . 'wp-admin/includes/upgrade.php';
        $charset = $wpdb->get_charset_collate();
        $sql = "CREATE TABLE {$table} (
            id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
            email varchar(190) NOT NULL,
            first_name varchar(100) NOT NULL DEFAULT '',
            last_name varchar(100) NOT NULL DEFAULT '',
            coupon_code varchar(64) NOT NULL DEFAULT '',
            coupon_id bigint(20) unsigned NOT NULL DEFAULT 0,
            created_at datetime NOT NULL,
            ip varchar(64) NOT NULL DEFAULT '',
            PRIMARY KEY  (id),
            UNIQUE KEY email (email),
            KEY coupon_code (coupon_code)
        ) {$charset};";
        // Suppress duplicate-create noise on race/reinstall
        $wpdb->hide_errors();
        dbDelta($sql);
        $wpdb->show_errors();
    }

    public static function enqueue(): void {
        if (!is_front_page() && !is_page()) {
            return;
        }
        wp_register_style('rs-newsletter', false);
        wp_enqueue_style('rs-newsletter');
        wp_add_inline_style('rs-newsletter', self::css());
        wp_register_script('rs-newsletter', false, [], null, true);
        wp_enqueue_script('rs-newsletter');
        wp_add_inline_script('rs-newsletter', self::js());
        wp_localize_script('rs-newsletter', 'rsNewsletter', [
            'ajaxUrl' => admin_url('admin-ajax.php'),
            'action' => self::ACTION,
            'nonce' => wp_create_nonce(self::ACTION),
        ]);
    }

    public static function render_mailpoet_alias($atts = []): string {
        // Only hijack form id=1 (homepage welcome discount)
        $id = isset($atts['id']) ? (string) $atts['id'] : '';
        if ($id !== '' && $id !== '1') {
            return '';
        }
        return self::render_form($atts);
    }

    public static function render_form($atts = []): string {
        ob_start();
        ?>
        <div class="rs-nl" id="hauhau">
          <form class="rs-nl__form" method="post" novalidate>
            <div class="rs-nl__row">
              <label class="rs-nl__field">
                <span>Imię</span>
                <input type="text" name="first_name" autocomplete="given-name" required maxlength="100" placeholder="Jan">
              </label>
              <label class="rs-nl__field">
                <span>Nazwisko</span>
                <input type="text" name="last_name" autocomplete="family-name" required maxlength="100" placeholder="Kowalski">
              </label>
            </div>
            <label class="rs-nl__field">
              <span>E-mail</span>
              <input type="email" name="email" autocomplete="email" required maxlength="190" placeholder="jan@example.com">
            </label>
            <p class="rs-nl__note">Zapisując się, otrzymasz jednorazowy kod <strong>−<?php echo (int) self::DISCOUNT_PERCENT; ?>%</strong> na pierwsze zamówienie (ważny <?php echo (int) self::COUPON_DAYS; ?> dni).</p>
            <button type="submit" class="rs-nl__submit">Odbierz rabat <?php echo (int) self::DISCOUNT_PERCENT; ?>%</button>
            <div class="rs-nl__msg" role="status" aria-live="polite" hidden></div>
          </form>
        </div>
        <?php
        return (string) ob_get_clean();
    }

    public static function handle_ajax(): void {
        if (!check_ajax_referer(self::ACTION, 'nonce', false)) {
            wp_send_json_error(['message' => 'Sesja wygasła. Odśwież stronę i spróbuj ponownie.'], 403);
        }

        $first = sanitize_text_field(wp_unslash($_POST['first_name'] ?? ''));
        $last = sanitize_text_field(wp_unslash($_POST['last_name'] ?? ''));
        $email = sanitize_email(wp_unslash($_POST['email'] ?? ''));

        if ($first === '' || $last === '' || !is_email($email)) {
            wp_send_json_error(['message' => 'Uzupełnij imię, nazwisko i poprawny adres e-mail.'], 400);
        }

        if (!function_exists('wc_get_coupon_id_by_code')) {
            wp_send_json_error(['message' => 'Sklep jest chwilowo niedostępny. Spróbuj później.'], 500);
        }

        global $wpdb;
        $table = self::table_name();
        self::maybe_create_table();

        $existing = $wpdb->get_row($wpdb->prepare("SELECT * FROM {$table} WHERE email = %s", $email));
        if ($existing) {
            // Resend existing unused coupon if still valid
            $coupon = new WC_Coupon($existing->coupon_code);
            $still_ok = $coupon->get_id() && ((int) $coupon->get_usage_count() < 1);
            if ($still_ok) {
                $sent = self::send_email($email, $first, $existing->coupon_code);
                $msg = $sent
                    ? 'Ten e-mail jest już zapisany. Wysłaliśmy ponownie Twój kod na e-mail.'
                    : 'Ten e-mail jest już zapisany. Oto Twój kod (e-mail chwilowo niedostępny):';
                wp_send_json_success([
                    'message' => $msg,
                    'coupon' => $existing->coupon_code,
                    'email_sent' => (bool) $sent,
                ]);
            }
            wp_send_json_error(['message' => 'Ten adres e-mail jest już zapisany do newslettera (kod został już wykorzystany).'], 409);
        }

        $code = self::generate_unique_code();
        $coupon_id = self::create_coupon($code, $email);
        if (!$coupon_id) {
            wp_send_json_error(['message' => 'Nie udało się utworzyć kuponu. Spróbuj ponownie.'], 500);
        }

        $ok = $wpdb->insert($table, [
            'email' => $email,
            'first_name' => $first,
            'last_name' => $last,
            'coupon_code' => $code,
            'coupon_id' => $coupon_id,
            'created_at' => current_time('mysql'),
            'ip' => self::client_ip(),
        ], ['%s', '%s', '%s', '%s', '%d', '%s', '%s']);

        if (!$ok) {
            wp_send_json_error(['message' => 'Nie udało się zapisać. Spróbuj ponownie.'], 500);
        }

        $sent = self::send_email($email, $first, $code);
        $msg = $sent
            ? 'Dziękujemy! Kod rabatowy wysłaliśmy na e-mail — możesz też skopiować go poniżej.'
            : 'Dziękujemy! Zapisaliśmy Cię i wygenerowaliśmy kod. E-mail chwilowo nie wychodzi — użyj kodu poniżej.';
        wp_send_json_success([
            'message' => $msg,
            'coupon' => $code,
            'email_sent' => (bool) $sent,
        ]);
    }

    private static function generate_unique_code(): string {
        for ($i = 0; $i < 8; $i++) {
            $code = self::COUPON_PREFIX . strtoupper(wp_generate_password(8, false, false));
            if (!wc_get_coupon_id_by_code($code)) {
                return $code;
            }
        }
        return self::COUPON_PREFIX . strtoupper(substr(md5(uniqid((string) mt_rand(), true)), 0, 10));
    }

    private static function create_coupon(string $code, string $email): int {
        $coupon = new WC_Coupon();
        $coupon->set_code($code);
        $coupon->set_description('Newsletter Retriever Shop — jednorazowy −' . self::DISCOUNT_PERCENT . '%');
        $coupon->set_discount_type('percent');
        $coupon->set_amount(self::DISCOUNT_PERCENT);
        $coupon->set_individual_use(true);
        $coupon->set_usage_limit(1);
        $coupon->set_usage_limit_per_user(1);
        $coupon->set_email_restrictions([$email]);
        $coupon->set_date_expires(strtotime('+' . self::COUPON_DAYS . ' days'));
        $coupon->set_free_shipping(false);
        $id = $coupon->save();
        return (int) $id;
    }

    private static function send_email(string $email, string $first, string $code): bool {
        // Wysyłka przez magazyn (działający SMTP OVH) — pomijamy WP/MailPoet.
        $url = (string) get_option('rs_magazyn_mail_url', 'https://magazyn.retrievershop.pl/api/shop-mail/newsletter-welcome');
        $secret = (string) get_option('rs_magazyn_mail_secret', '');
        if ($url === '' || $secret === '') {
            error_log('RS_Newsletter: brak rs_magazyn_mail_url / rs_magazyn_mail_secret');
            return false;
        }

        $payload = wp_json_encode([
            'email' => $email,
            'first_name' => $first,
            'coupon_code' => $code,
            'discount_percent' => self::DISCOUNT_PERCENT,
            'valid_days' => self::COUPON_DAYS,
            'shop_url' => home_url('/produkty/'),
        ]);
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
            error_log('RS_Newsletter magazyn mail error: ' . $response->get_error_message());
            return false;
        }
        $code_http = (int) wp_remote_retrieve_response_code($response);
        if ($code_http < 200 || $code_http >= 300) {
            error_log('RS_Newsletter magazyn mail HTTP ' . $code_http . ' body=' . wp_remote_retrieve_body($response));
            return false;
        }
        return true;
    }

    private static function client_ip(): string {
        $ip = $_SERVER['REMOTE_ADDR'] ?? '';
        return is_string($ip) ? substr($ip, 0, 64) : '';
    }

    private static function css(): string {
        return <<<'CSS'
.rs-nl{max-width:480px;margin:0 auto}
.rs-nl__form{display:grid;gap:12px}
.rs-nl__row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:560px){.rs-nl__row{grid-template-columns:1fr}}
.rs-nl__field{display:grid;gap:6px;font-size:14px;color:#1A3333}
.rs-nl__field span{font-weight:600}
.rs-nl__field input{border:1px solid #d9d3c9;border-radius:6px;padding:12px 14px;font:inherit;background:#fff}
.rs-nl__field input:focus{outline:2px solid #C45C3E;outline-offset:1px;border-color:#C45C3E}
.rs-nl__note{margin:0;font-size:13px;color:#5A6B6B;line-height:1.45}
.rs-nl__submit{appearance:none;border:0;border-radius:6px;background:#C45C3E;color:#fff;font:inherit;font-weight:600;padding:14px 18px;cursor:pointer}
.rs-nl__submit:disabled{opacity:.65;cursor:wait}
.rs-nl__msg{font-size:14px;padding:12px 14px;border-radius:6px;background:#F3F0EB}
.rs-nl__msg.is-ok{background:#e8f5e9;color:#1b5e20}
.rs-nl__msg.is-err{background:#fdecea;color:#8a1c14}
CSS;
    }

    private static function js(): string {
        return <<<'JS'
(function(){
  function ready(fn){ if(document.readyState!=='loading') fn(); else document.addEventListener('DOMContentLoaded', fn); }
  ready(function(){
    document.querySelectorAll('.rs-nl__form').forEach(function(form){
      form.addEventListener('submit', function(e){
        e.preventDefault();
        if(!window.rsNewsletter) return;
        var btn = form.querySelector('.rs-nl__submit');
        var msg = form.querySelector('.rs-nl__msg');
        var fd = new FormData(form);
        fd.append('action', rsNewsletter.action);
        fd.append('nonce', rsNewsletter.nonce);
        btn.disabled = true;
        msg.hidden = true;
        msg.classList.remove('is-ok','is-err');
        fetch(rsNewsletter.ajaxUrl, { method:'POST', body: fd, credentials:'same-origin' })
          .then(function(r){ return r.json().then(function(j){ return {ok:r.ok, j:j}; }); })
          .then(function(res){
            var data = (res.j && res.j.data) || {};
            var message = data.message || (res.j && res.j.message) || 'Coś poszło nie tak.';
            if (res.j && res.j.success && data.coupon) {
              message += ' Kod: ' + data.coupon;
            }
            msg.hidden = false;
            msg.textContent = message;
            msg.classList.add(res.j && res.j.success ? 'is-ok' : 'is-err');
            if(res.j && res.j.success) form.reset();
          })
          .catch(function(){
            msg.hidden = false;
            msg.textContent = 'Błąd połączenia. Spróbuj ponownie.';
            msg.classList.add('is-err');
          })
          .finally(function(){ btn.disabled = false; });
      });
    });
  });
})();
JS;
    }
}

RS_Newsletter::init();
