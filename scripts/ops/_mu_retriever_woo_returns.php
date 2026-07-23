<?php
/**
 * Plugin Name: Retriever Woo Returns Bridge
 * Description: Most WebToffee EU Withdrawal → magazyn (webhook + REST lista).
 */
if (!defined('ABSPATH')) {
    exit;
}

/**
 * Shared secret: WP option retriever_woo_return_secret, else WOO_WEBHOOK_SECRET env,
 * else empty (webhook disabled).
 */
function rs_woo_return_secret(): string {
    $opt = (string) get_option('retriever_woo_return_secret', '');
    if ($opt !== '') {
        return $opt;
    }
    $env = (string) (getenv('WOO_WEBHOOK_SECRET') ?: '');
    return $env;
}

function rs_woo_return_magazyn_url(): string {
    $url = (string) get_option('retriever_woo_return_webhook_url', '');
    if ($url !== '') {
        return $url;
    }
    return 'https://magazyn.retrievershop.pl/webhooks/woo-return';
}

function rs_woo_return_sign(string $body): string {
    $secret = rs_woo_return_secret();
    if ($secret === '') {
        return '';
    }
    return hash_hmac('sha256', $body, $secret);
}

/**
 * Build payload from WebToffee request object / row.
 *
 * @param object|array $request Wbte_Ewb_Request or array-like.
 * @param WC_Order|null $order
 */
function rs_woo_return_build_payload($request, $order = null): array {
    $id = 0;
    $order_id = 0;
    $order_number = '';
    $email = '';
    $status = 'pending';
    $reason = '';
    $items = [];
    $created_at = gmdate('c');
    $customer_name = '';

    if (is_object($request)) {
        $id = (int) ($request->id ?? 0);
        $order_id = (int) ($request->order_id ?? 0);
        $order_number = (string) ($request->order_number ?? '');
        $email = (string) ($request->customer_email ?? '');
        $status = (string) ($request->status ?? 'pending');
        $reason = (string) ($request->reason ?? '');
        if (isset($request->created_at) && $request->created_at) {
            $created_at = is_string($request->created_at)
                ? $request->created_at
                : gmdate('c', strtotime((string) $request->created_at));
        }
        if (method_exists($request, 'get_items')) {
            $raw_items = $request->get_items();
        } elseif (isset($request->items_json)) {
            $raw_items = json_decode((string) $request->items_json, true) ?: [];
        } else {
            $raw_items = [];
        }
        if (is_array($raw_items)) {
            foreach ($raw_items as $item) {
                if (!is_array($item)) {
                    continue;
                }
                $items[] = [
                    'name' => (string) ($item['name'] ?? $item['product_name'] ?? 'Produkt'),
                    'quantity' => (int) ($item['quantity'] ?? 1),
                    'product_id' => $item['product_id'] ?? null,
                    'variation_id' => $item['variation_id'] ?? null,
                    'sku' => $item['sku'] ?? null,
                    'ean' => $item['ean'] ?? $item['barcode'] ?? null,
                    'price_brutto' => $item['price'] ?? $item['total'] ?? $item['price_brutto'] ?? null,
                    'line_item_id' => $item['item_id'] ?? $item['line_item_id'] ?? null,
                ];
            }
        }
    } elseif (is_array($request)) {
        $id = (int) ($request['id'] ?? 0);
        $order_id = (int) ($request['order_id'] ?? 0);
        $order_number = (string) ($request['order_number'] ?? '');
        $email = (string) ($request['customer_email'] ?? '');
        $status = (string) ($request['status'] ?? 'pending');
        $reason = (string) ($request['reason'] ?? '');
        $created_at = (string) ($request['created_at'] ?? $created_at);
        $decoded = json_decode((string) ($request['items_json'] ?? '[]'), true) ?: [];
        if (is_array($decoded)) {
            foreach ($decoded as $item) {
                if (!is_array($item)) {
                    continue;
                }
                $items[] = [
                    'name' => (string) ($item['name'] ?? $item['product_name'] ?? 'Produkt'),
                    'quantity' => (int) ($item['quantity'] ?? 1),
                    'product_id' => $item['product_id'] ?? null,
                    'variation_id' => $item['variation_id'] ?? null,
                    'sku' => $item['sku'] ?? null,
                    'ean' => $item['ean'] ?? $item['barcode'] ?? null,
                    'price_brutto' => $item['price'] ?? $item['total'] ?? $item['price_brutto'] ?? null,
                    'line_item_id' => $item['item_id'] ?? $item['line_item_id'] ?? null,
                ];
            }
        }
    }

    if (!$order && $order_id && function_exists('wc_get_order')) {
        $order = wc_get_order($order_id);
    }
    if ($order instanceof WC_Order) {
        if ($order_number === '') {
            $order_number = (string) $order->get_order_number();
        }
        if ($email === '') {
            $email = (string) $order->get_billing_email();
        }
        $customer_name = trim($order->get_formatted_billing_full_name());
        if ($customer_name === '') {
            $customer_name = trim($order->get_billing_first_name() . ' ' . $order->get_billing_last_name());
        }
    }

    return [
        'withdrawal_id' => $id,
        'order_id' => $order_id,
        'order_number' => $order_number,
        'customer_email' => $email,
        'customer_name' => $customer_name,
        'status' => $status,
        'reason' => $reason,
        'items' => $items,
        'created_at' => $created_at,
    ];
}

function rs_woo_return_post_to_magazyn(array $payload): ?array {
    $secret = rs_woo_return_secret();
    $url = rs_woo_return_magazyn_url();
    if ($secret === '' || $url === '') {
        return null;
    }
    $body = wp_json_encode($payload);
    if (!is_string($body) || $body === '') {
        return null;
    }
    $sig = rs_woo_return_sign($body);
    // Blocking: potrzebujemy instruction_token do redirectu klienta.
    $response = wp_remote_post($url, [
        'timeout' => 20,
        'blocking' => true,
        'headers' => [
            'Content-Type' => 'application/json',
            'X-Retriever-Signature' => $sig,
            'User-Agent' => 'retrievershop-wp-returns/1.1',
        ],
        'body' => $body,
    ]);
    if (is_wp_error($response)) {
        return null;
    }
    $code = (int) wp_remote_retrieve_response_code($response);
    $raw = (string) wp_remote_retrieve_body($response);
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        return ['ok' => false, 'http' => $code];
    }
    $data['http'] = $code;
    return $data;
}

function rs_woo_return_store_instruction_redirect(?array $result): void {
    if (!is_array($result) || empty($result['instruction_url'])) {
        $token = is_array($result) ? (string) ($result['instruction_token'] ?? '') : '';
        if ($token === '') {
            return;
        }
        $url = home_url('/instrukcja-zwrotu/?t=' . rawurlencode($token));
    } else {
        $url = (string) $result['instruction_url'];
        // Preferuj lokalną stronę WP z tokenem z magazynu.
        $token = (string) ($result['instruction_token'] ?? '');
        if ($token !== '') {
            $url = home_url('/instrukcja-zwrotu/?t=' . rawurlencode($token));
        }
    }
    if (is_user_logged_in()) {
        set_transient('rs_return_instr_' . get_current_user_id(), $url, 15 * MINUTE_IN_SECONDS);
    }
    // Cookie dla gościa / backup
    if (!headers_sent()) {
        setcookie(
            'rs_return_instr',
            rawurlencode($url),
            [
                'expires' => time() + 15 * MINUTE_IN_SECONDS,
                'path' => defined('COOKIEPATH') && COOKIEPATH ? COOKIEPATH : '/',
                'domain' => defined('COOKIE_DOMAIN') ? COOKIE_DOMAIN : '',
                'secure' => is_ssl(),
                'httponly' => true,
                'samesite' => 'Lax',
            ]
        );
    }
}

add_action('wbte_ewb_request_submitted', static function ($request, $order = null) {
    $payload = rs_woo_return_build_payload($request, $order);
    if (empty($payload['withdrawal_id']) || empty($payload['order_id'])) {
        return;
    }
    $result = rs_woo_return_post_to_magazyn($payload);
    rs_woo_return_store_instruction_redirect($result);
}, 10, 2);

add_action('template_redirect', static function () {
    if (!isset($_GET['wbte_ewb_submitted']) || (string) wp_unslash($_GET['wbte_ewb_submitted']) !== '1') { // phpcs:ignore WordPress.Security.NonceVerification.Recommended
        return;
    }
    $url = '';
    if (is_user_logged_in()) {
        $key = 'rs_return_instr_' . get_current_user_id();
        $url = (string) get_transient($key);
        if ($url !== '') {
            delete_transient($key);
        }
    }
    if ($url === '' && !empty($_COOKIE['rs_return_instr'])) {
        $url = rawurldecode((string) wp_unslash($_COOKIE['rs_return_instr']));
        if (!headers_sent()) {
            setcookie('rs_return_instr', '', time() - 3600, defined('COOKIEPATH') && COOKIEPATH ? COOKIEPATH : '/');
        }
    }
    if ($url === '' || strpos($url, 'instrukcja-zwrotu') === false) {
        return;
    }
    wp_safe_redirect($url);
    exit;
}, 5);

add_action('rest_api_init', static function () {
    register_rest_route('retrievershop/v1', '/withdrawals', [
        'methods' => 'GET',
        'permission_callback' => static function (WP_REST_Request $request) {
            $secret = rs_woo_return_secret();
            if ($secret === '') {
                return false;
            }
            $provided = (string) $request->get_header('X-Retriever-Secret');
            if ($provided === '') {
                $provided = (string) $request->get_param('secret');
            }
            return hash_equals($secret, $provided);
        },
        'callback' => static function (WP_REST_Request $request) {
            global $wpdb;
            $table = $wpdb->prefix . 'wbte_ewb_withdrawals';
            $exists = $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table));
            if (!$exists) {
                return new WP_REST_Response(['withdrawals' => [], 'error' => 'table_missing'], 200);
            }
            $after_id = max(0, (int) $request->get_param('after_id'));
            $limit = min(100, max(1, (int) ($request->get_param('limit') ?: 50)));
            $status = (string) ($request->get_param('status') ?: '');
            $sql = "SELECT * FROM {$table} WHERE id > %d";
            $params = [$after_id];
            if ($status !== '') {
                $sql .= ' AND status = %s';
                $params[] = $status;
            }
            $sql .= ' ORDER BY id ASC LIMIT %d';
            $params[] = $limit;
            // phpcs:ignore WordPress.DB.PreparedSQL.NotPrepared
            $rows = $wpdb->get_results($wpdb->prepare($sql, $params), ARRAY_A) ?: [];
            $out = [];
            foreach ($rows as $row) {
                $out[] = rs_woo_return_build_payload($row);
            }
            return new WP_REST_Response(['withdrawals' => $out], 200);
        },
    ]);
});

/**
 * Wymagaj powodu odstąpienia (ustawienie WebToffee).
 */
add_action('init', static function () {
    $settings = get_option('wbte_ewb_settings');
    if (!is_array($settings)) {
        return;
    }
    if (($settings['reason_required'] ?? '') === 'yes') {
        return;
    }
    $settings['reason_required'] = 'yes';
    update_option('wbte_ewb_settings', $settings, false);
}, 20);

/**
 * Polskie etykiety formularza WebToffee (bez patchowania vendor).
 */
add_filter('gettext', static function ($translation, $text, $domain) {
    if ($domain !== 'wt-eu-withdrawal-button') {
        return $translation;
    }
    static $map = [
        'Order' => 'Zamówienie',
        '-- Select an order --' => '-- Wybierz zamówienie --',
        'Items to withdraw' => 'Produkty do zwrotu',
        'Loading items...' => 'Ładowanie produktów…',
        'Email' => 'E-mail',
        'First name' => 'Imię',
        'Last name' => 'Nazwisko',
        'Reason for withdrawal' => 'Powód odstąpienia',
        'Submit Withdrawal Request' => 'Wyślij wniosek o odstąpienie',
        'You currently have no orders eligible for withdrawal.' => 'Nie masz obecnie zamówień uprawnionych do odstąpienia od umowy.',
        'required' => 'wymagane',
    ];
    return $map[$text] ?? $translation;
}, 20, 3);

/**
 * Czy bieżąca strona to formularz odstąpienia WebToffee.
 */
function rs_woo_return_is_form_page(): bool {
    $settings = get_option('wbte_ewb_settings');
    $page_id = is_array($settings) ? (int) ($settings['withdrawal_page'] ?? 0) : 0;
    if ($page_id > 0 && is_page($page_id)) {
        return true;
    }
    if (!is_page()) {
        return false;
    }
    global $post;
    if (!$post instanceof WP_Post) {
        return false;
    }
    $content = (string) $post->post_content;
    return strpos($content, 'wbte_ewb_withdrawal_form') !== false
        || strpos($content, 'wbte-ewb-withdrawal-form') !== false;
}

/**
 * UX formularza: dropdown powodów + blokada zamówienia przy ?order_id=.
 */
add_action('wp_footer', static function () {
    if (is_admin() || !rs_woo_return_is_form_page()) {
        return;
    }

    $reasons = [
        'Zmiana decyzji — produkt nie jest mi potrzebny',
        'Zły rozmiar',
        'Inny kolor / wariant niż oczekiwany',
        'Produkt uszkodzony lub wadliwy',
        'Produkt niezgodny z opisem',
        'Opóźniona dostawa',
        'Inne',
    ];
    $reasons_json = wp_json_encode($reasons, JSON_UNESCAPED_UNICODE);
    if (!is_string($reasons_json)) {
        $reasons_json = '[]';
    }
    ?>
<style id="rs-woo-returns-form-css">
.wbte-ewb-form--logged-in .wbte-ewb-order-select.rs-locked{pointer-events:none;background:#f3f4f6;color:#111;opacity:1;cursor:default;}
.wbte-ewb-form-row .rs-reason-select{width:100%;max-width:100%;}
.wbte-ewb-form-row #wbte_ewb_reason.rs-reason-other-only{margin-top:.75rem;}
.wbte-ewb-form-row #wbte_ewb_reason.rs-reason-hidden{display:none!important;}
</style>
<script id="rs-woo-returns-form-js">
(function(){
  function enhance(){
    var form=document.getElementById('wbte-ewb-withdrawal-form');
    if(!form||form.dataset.rsEnhanced==='1'){return;}
    form.dataset.rsEnhanced='1';

    var orderSel=document.getElementById('wbte_ewb_order_id');
    if(orderSel){
      var params=new URLSearchParams(window.location.search);
      var oid=parseInt(params.get('order_id')||'0',10);
      if(oid>0){
        orderSel.value=String(oid);
        if(orderSel.value===String(oid)){
          orderSel.classList.add('rs-locked');
          orderSel.setAttribute('aria-readonly','true');
          orderSel.addEventListener('mousedown',function(e){e.preventDefault();});
          orderSel.addEventListener('keydown',function(e){e.preventDefault();});
          orderSel.dispatchEvent(new Event('change',{bubbles:true}));
        }
      }
    }

    var ta=document.getElementById('wbte_ewb_reason');
    if(!ta||ta.dataset.rsReasonSelect==='1'){return;}
    ta.dataset.rsReasonSelect='1';
    var reasons=<?php echo $reasons_json; ?>;
    var wrap=document.createElement('div');
    wrap.className='rs-reason-wrap';
    var sel=document.createElement('select');
    sel.id='rs_ewb_reason_select';
    sel.className='rs-reason-select input-text';
    sel.required=!!ta.required;
    var opt0=document.createElement('option');
    opt0.value='';
    opt0.textContent='-- Wybierz powód --';
    sel.appendChild(opt0);
    reasons.forEach(function(r){
      var o=document.createElement('option');
      o.value=r;
      o.textContent=r;
      sel.appendChild(o);
    });
    ta.classList.add('rs-reason-hidden');
    ta.removeAttribute('required');
    ta.parentNode.insertBefore(wrap, ta);
    wrap.appendChild(sel);
    wrap.appendChild(ta);

    function sync(){
      var v=sel.value;
      if(v==='Inne'){
        ta.classList.remove('rs-reason-hidden');
        ta.classList.add('rs-reason-other-only');
        ta.required=!!sel.required;
        if(!ta.value||reasons.indexOf(ta.value)>=0){ta.value='';}
        ta.placeholder='Opisz krótko powód…';
      }else{
        ta.classList.add('rs-reason-hidden');
        ta.classList.remove('rs-reason-other-only');
        ta.required=false;
        ta.value=v;
      }
    }
    sel.addEventListener('change',sync);
    form.addEventListener('submit',function(e){
      sync();
      if(sel.required && !sel.value){
        e.preventDefault();
        sel.focus();
        return;
      }
      if(sel.value==='Inne' && !String(ta.value||'').trim()){
        e.preventDefault();
        ta.focus();
      }
    });
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',enhance);
  }else{enhance();}
})();
</script>
    <?php
}, 40);

/**
 * Shortcode [rs_return_instructions] — wybór metody odesłania po wniosku.
 * API magazynu: GET/POST /api/shop/return-instructions/{token}
 */
add_shortcode('rs_return_instructions', static function () {
    $token = isset($_GET['t']) ? sanitize_text_field(wp_unslash($_GET['t'])) : ''; // phpcs:ignore WordPress.Security.NonceVerification.Recommended
    $api_base = 'https://magazyn.retrievershop.pl';
    ob_start();
    ?>
<div class="rs-return-instr" id="rs-return-instr" data-api="<?php echo esc_url($api_base); ?>" data-token="<?php echo esc_attr($token); ?>">
  <p class="rs-return-instr__loading">Ładowanie instrukcji zwrotu…</p>
  <div class="rs-return-instr__body" hidden></div>
  <p class="rs-return-instr__error" hidden></p>
</div>
<style>
.rs-return-instr{max-width:640px;margin:0 auto;font-size:1rem;line-height:1.55}
.rs-return-instr h2{margin:0 0 .75rem;font-size:1.4rem}
.rs-return-instr__choices{display:grid;gap:12px;margin:1.25rem 0}
.rs-return-instr__btn{display:block;width:100%;text-align:left;padding:14px 16px;border:1px solid #d0d0d0;border-radius:8px;background:#fff;cursor:pointer;font:inherit}
.rs-return-instr__btn:hover{border-color:#c45c3e}
.rs-return-instr__btn[disabled]{opacity:.55;cursor:not-allowed}
.rs-return-instr__btn strong{display:block;margin-bottom:4px}
.rs-return-instr__meta{color:#555;font-size:.95rem}
.rs-return-instr__box{background:#f6f6f7;border-radius:8px;padding:16px;margin:1rem 0}
.rs-return-instr__code{font-size:1.6rem;letter-spacing:.08em;font-weight:700}
.rs-return-instr__error{color:#b00020}
.rs-return-instr__phone{margin:12px 0;display:flex;gap:8px;flex-wrap:wrap}
.rs-return-instr__phone input{flex:1;min-width:160px;padding:8px 10px}
</style>
<script>
(function(){
  var root=document.getElementById('rs-return-instr');
  if(!root)return;
  var api=(root.getAttribute('data-api')||'').replace(/\/$/,'');
  var token=root.getAttribute('data-token')||'';
  var loading=root.querySelector('.rs-return-instr__loading');
  var body=root.querySelector('.rs-return-instr__body');
  var err=root.querySelector('.rs-return-instr__error');

  function showErr(msg){
    loading.hidden=true; body.hidden=true; err.hidden=false; err.textContent=msg||'Błąd';
  }
  function esc(s){
    return String(s||'').replace(/[&<>"']/g,function(c){return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]);});
  }
  function addrHtml(a){
    if(!a)return '';
    return '<div class="rs-return-instr__box"><strong>'+esc(a.company)+'</strong><br>'+
      esc(a.name)+'<br>'+esc(a.street)+'<br>'+esc(a.postcode)+' '+esc(a.city)+
      '<br>Tel: '+esc(a.phone)+'</div>';
  }
  function render(data){
    loading.hidden=true; err.hidden=true; body.hidden=false;
    var html='';
    html+='<p class="rs-return-instr__meta">Zamówienie <strong>#'+esc(data.order_number||data.order_id)+'</strong>';
    if(data.withdrawal_id) html+=' · zgłoszenie #'+esc(data.withdrawal_id);
    html+='</p>';

    if(data.method==='self'){
      html+='<h2>Zwrot własny</h2>';
      html+='<p>Wyślij paczkę do <strong>'+esc((data.deadline||'').slice(0,10))+'</strong> (14 dni od zgłoszenia) na adres:</p>';
      html+=addrHtml(data.address);
      html+='<p>Na paczce napisz nr zamówienia. Po nadaniu warto podać nam numer przesyłki. Wysłaliśmy też e-mail z tą instrukcją.</p>';
      body.innerHTML=html; return;
    }
    if(data.method==='inpost_buyer' && data.return_code){
      html+='<h2>Szybki zwrot InPost</h2>';
      html+='<div class="rs-return-instr__box"><div>Kod nadania</div><div class="rs-return-instr__code">'+esc(data.return_code)+'</div>';
      if(data.return_code_expires_at) html+='<div class="rs-return-instr__meta">Ważny do: '+esc(data.return_code_expires_at)+'</div>';
      html+='</div>';
      html+='<p>Nadasz w dowolnym Paczkomacie (opcja zwrotu). <strong>Opłatę pobierze InPost przy nadaniu.</strong> Wysłaliśmy kod też e-mailem.</p>';
      body.innerHTML=html; return;
    }

    html+='<h2>Jak chcesz odesłać zwrot?</h2>';
    html+='<div class="rs-return-instr__choices">';
    html+='<button type="button" class="rs-return-instr__btn" data-method="inpost_buyer"'+(data.inpost_available?'':' disabled')+'>';
    html+='<strong>Szybki zwrot InPost</strong>';
    html+= data.inpost_available
      ? '<span>Kod do Paczkomatu — opłatę pobierze InPost przy nadaniu.</span>'
      : '<span>Wkrótce — czekamy na aktywację Returns Portal u InPost. Wybierz zwrot własny.</span>';
    html+='</button>';
    html+='<button type="button" class="rs-return-instr__btn" data-method="self"><strong>Zwrot własny</strong><span>Wyślij na nasz adres w Legnicy w ciągu 14 dni od zgłoszenia.</span></button>';
    html+='</div>';
    html+='<div class="rs-return-instr__phone" id="rs-phone-row" hidden>';
    html+='<label for="rs-phone">Telefon do kodu InPost (9 cyfr)</label>';
    html+='<input id="rs-phone" type="tel" inputmode="numeric" placeholder="500600700" maxlength="15">';
    html+='</div>';
    html+='<p class="rs-return-instr__meta" id="rs-choose-status" hidden></p>';
    body.innerHTML=html;

    body.querySelectorAll('[data-method]').forEach(function(btn){
      btn.addEventListener('click', function(){
        var method=btn.getAttribute('data-method');
        var phoneEl=document.getElementById('rs-phone');
        var phoneRow=document.getElementById('rs-phone-row');
        var status=document.getElementById('rs-choose-status');
        if(method==='inpost_buyer' && !data.has_phone){
          phoneRow.hidden=false;
          if(!phoneEl.value.trim()){ phoneEl.focus(); status.hidden=false; status.textContent='Podaj numer telefonu.'; return; }
        }
        status.hidden=false; status.textContent='Zapisywanie…';
        body.querySelectorAll('button').forEach(function(b){b.disabled=true;});
        var payload={method:method, pack_size:'A'};
        if(phoneEl && phoneEl.value.trim()) payload.phone=phoneEl.value.trim();
        fetch(api+'/api/shop/return-instructions/'+encodeURIComponent(token)+'/choose',{
          method:'POST',
          headers:{'Content-Type':'application/json','Accept':'application/json'},
          body:JSON.stringify(payload)
        }).then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})
          .then(function(res){
            if(!res.j || !res.j.ok){
              status.textContent=(res.j && (res.j.message||res.j.error)) || 'Nie udało się zapisać wyboru.';
              body.querySelectorAll('button').forEach(function(b){
                if(b.getAttribute('data-method')==='inpost_buyer' && !data.inpost_available) return;
                b.disabled=false;
              });
              if(res.j && res.j.error==='phone_required'){ phoneRow.hidden=false; }
              return;
            }
            render(res.j);
          }).catch(function(){
            status.textContent='Błąd sieci. Spróbuj ponownie.';
            body.querySelectorAll('button').forEach(function(b){b.disabled=false;});
          });
      });
    });
  }

  if(!token){ showErr('Brak tokenu instrukcji. Wróć do formularza odstąpienia i wyślij wniosek ponownie.'); return; }
  fetch(api+'/api/shop/return-instructions/'+encodeURIComponent(token),{headers:{'Accept':'application/json'}})
    .then(function(r){return r.json().then(function(j){return {ok:r.ok,j:j};});})
    .then(function(res){
      if(!res.j || !res.j.ok){ showErr('Nie znaleziono zgłoszenia zwrotu.'); return; }
      render(res.j);
    }).catch(function(){ showErr('Nie udało się połączyć z magazynem.'); });
})();
</script>
    <?php
    return (string) ob_get_clean();
});
