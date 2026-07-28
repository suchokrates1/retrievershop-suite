<?php
/**
 * Plugin Name: Retriever Cart Drawer
 * Description: Elegant right-side animated cart drawer (replaces Blocksy dropdown).
 */
if (!defined('ABSPATH')) {
    exit;
}

add_filter('gettext', static function ($translated, $text, $domain) {
    if ($text === 'No products in the cart.') {
        return "Tw\u{00F3}j koszyk jest pusty.";
    }
    return $translated;
}, 99, 3);

/* Mini-cart CTAs live in drawer footer — strip Woo/Blocksy duplicates from widget body. */
add_action('wp', static function () {
    remove_action('woocommerce_widget_shopping_cart_buttons', 'woocommerce_widget_shopping_cart_button_view_cart', 10);
    remove_action('woocommerce_widget_shopping_cart_buttons', 'woocommerce_widget_shopping_cart_proceed_to_checkout', 20);
}, 20);

/* Markup before wp_enqueue footer scripts (prio 20) so inline JS can bind. */
add_action('wp_footer', static function () {
    if (is_admin() || !function_exists('WC')) {
        return;
    }
    if (null === WC()->cart && function_exists('wc_load_cart')) {
        wc_load_cart();
    }
    if (!WC()->cart) {
        return;
    }
    $cart_url = function_exists('wc_get_cart_url') ? wc_get_cart_url() : home_url('/koszyk/');
    $checkout_url = function_exists('wc_get_checkout_url') ? wc_get_checkout_url() : home_url('/kasa/');
    $count = (int) WC()->cart->get_cart_contents_count();
    $empty = WC()->cart->is_empty();
    ?>
<div id="rs-cart-drawer" class="rs-cart-drawer" aria-hidden="true">
  <div class="rs-cart-drawer__backdrop" data-rs-cart-close tabindex="-1"></div>
  <aside class="rs-cart-drawer__panel" role="dialog" aria-modal="true" aria-labelledby="rs-cart-drawer-title" tabindex="-1">
    <header class="rs-cart-drawer__head">
      <div class="rs-cart-drawer__head-text">
        <p class="rs-cart-drawer__eyebrow">Retriever Shop</p>
        <h2 id="rs-cart-drawer-title">Koszyk</h2>
      </div>
      <button type="button" class="rs-cart-drawer__close" data-rs-cart-close aria-label="Zamknij koszyk">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
        </svg>
      </button>
    </header>
    <div class="rs-cart-drawer__body" data-rs-cart-mount>
      <div class="widget_shopping_cart_content" data-count="<?php echo esc_attr((string) $count); ?>">
        <?php woocommerce_mini_cart(); ?>
      </div>
    </div>
    <footer class="rs-cart-drawer__foot" data-rs-cart-foot <?php echo $empty ? 'hidden' : ''; ?>>
      <a class="rs-cart-drawer__btn rs-cart-drawer__btn--ghost" href="<?php echo esc_url($cart_url); ?>">Zobacz koszyk</a>
      <a class="rs-cart-drawer__btn rs-cart-drawer__btn--solid" href="<?php echo esc_url($checkout_url); ?>">Do kasy</a>
    </footer>
  </aside>
</div>
    <?php
}, 5);

add_action('wp_head', static function () {
    if (is_admin() || !function_exists('WC')) {
        return;
    }
    echo '<style id="rs-cart-drawer-css">
/* Kill Blocksy dropdown; drawer owns the mini-cart */
.ct-header-cart:hover .ct-cart-content,
.ct-header-cart .ct-cart-content{
  display:none!important;
  visibility:hidden!important;
  opacity:0!important;
  pointer-events:none!important;
}
.rs-cart-drawer{
  --rs-cd-forest:#17383E;
  --rs-cd-ink:#1A3333;
  --rs-cd-muted:#5A6B6B;
  --rs-cd-surface:#FFFCFA;
  --rs-cd-accent:#C45C3E;
  --rs-cd-accent-deep:#9E4A32;
  --rs-cd-line:rgba(23,56,62,.12);
  --rs-cd-ease:cubic-bezier(.22,1,.36,1);
  position:fixed;
  inset:0;
  z-index:100050;
  pointer-events:none;
}
.rs-cart-drawer.is-open{pointer-events:auto;}
.rs-cart-drawer__backdrop{
  position:absolute;
  inset:0;
  background:rgba(16,41,46,.48);
  backdrop-filter:blur(3px);
  -webkit-backdrop-filter:blur(3px);
  opacity:0;
  transition:opacity .38s var(--rs-cd-ease);
}
.rs-cart-drawer.is-open .rs-cart-drawer__backdrop{opacity:1;}
.rs-cart-drawer__panel{
  position:absolute;
  top:0;
  right:0;
  display:flex;
  flex-direction:column;
  width:min(420px,100vw);
  height:100%;
  max-height:100dvh;
  background:var(--rs-cd-surface);
  color:var(--rs-cd-ink);
  box-shadow:-24px 0 60px rgba(16,41,46,.22);
  transform:translate3d(104%,0,0);
  transition:transform .44s var(--rs-cd-ease);
  outline:none;
}
.rs-cart-drawer.is-open .rs-cart-drawer__panel{transform:translate3d(0,0,0);}
.rs-cart-drawer__head{
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:16px;
  padding:22px 22px 18px;
  background:linear-gradient(165deg,var(--rs-cd-forest) 0%,#1f4a52 100%);
  color:#FFFCFA;
}
.rs-cart-drawer__eyebrow{
  margin:0 0 4px;
  font-size:11px;
  letter-spacing:.14em;
  text-transform:uppercase;
  opacity:.72;
  font-family:Poppins,sans-serif;
}
.rs-cart-drawer__head h2{
  margin:0;
  font-family:Poppins,sans-serif;
  font-size:1.55rem;
  font-weight:700;
  line-height:1.15;
  color:#FFFCFA;
}
.rs-cart-drawer__close{
  appearance:none;
  border:1px solid rgba(255,252,250,.28);
  background:rgba(255,252,250,.08);
  color:#FFFCFA;
  width:42px;
  height:42px;
  border-radius:999px;
  display:inline-flex;
  align-items:center;
  justify-content:center;
  cursor:pointer;
  transition:background .2s ease, transform .2s ease, border-color .2s ease;
}
.rs-cart-drawer__close:hover{
  background:rgba(255,252,250,.16);
  border-color:rgba(255,252,250,.5);
  transform:rotate(90deg);
}
.rs-cart-drawer__body{
  flex:1 1 auto;
  overflow:auto;
  padding:8px 18px 20px;
  -webkit-overflow-scrolling:touch;
}
.rs-cart-drawer__body .ct-cart-content{
  display:block!important;
  visibility:visible!important;
  opacity:1!important;
  pointer-events:auto!important;
  position:static!important;
  width:auto!important;
  max-width:none!important;
  height:auto!important;
  max-height:none!important;
  padding:0!important;
  margin:0!important;
  background:transparent!important;
  box-shadow:none!important;
  border:0!important;
  transform:none!important;
}
.rs-cart-drawer__body .woocommerce-mini-cart{
  --mini-cart-items-spacing:0;
  list-style:none;
  margin:0;
  padding:0;
}
.rs-cart-drawer__body .woocommerce-mini-cart-item,
.rs-cart-drawer__body .woocommerce-mini-cart li{
  display:grid!important;
  grid-template-columns:64px 1fr auto!important;
  grid-column-gap:14px!important;
  align-items:center!important;
  padding:16px 0!important;
  margin:0!important;
  border-bottom:1px solid var(--rs-cd-line)!important;
  background:transparent!important;
}
.rs-cart-drawer__body .woocommerce-mini-cart-item img,
.rs-cart-drawer__body .woocommerce-mini-cart li img{
  width:64px!important;
  height:64px!important;
  max-width:64px!important;
  object-fit:cover!important;
  border-radius:10px;
  background:#EEF2F1;
}
.rs-cart-drawer__body .product-title{
  font-family:Poppins,sans-serif;
  font-size:14px!important;
  font-weight:600!important;
  line-height:1.35!important;
  color:var(--rs-cd-ink)!important;
}
.rs-cart-drawer__body .quantity,
.rs-cart-drawer__body .amount{
  font-size:13px!important;
  color:var(--rs-cd-muted)!important;
}
.rs-cart-drawer__body .remove_from_cart_button{
  color:var(--rs-cd-muted)!important;
  opacity:.85;
}
.rs-cart-drawer__body .remove_from_cart_button:hover{
  color:var(--rs-cd-accent)!important;
  opacity:1;
}
.rs-cart-drawer__body .woocommerce-mini-cart__empty-message{
  margin:48px 8px;
  text-align:center;
  font-family:Poppins,sans-serif;
  font-size:1.05rem;
  color:var(--rs-cd-muted);
  line-height:1.5;
}
.rs-cart-drawer__body .woocommerce-mini-cart__total,
.rs-cart-drawer__body .total{
  display:flex;
  justify-content:space-between;
  align-items:baseline;
  gap:12px;
  margin:18px 0 8px!important;
  padding:14px 0 0!important;
  border-top:1px solid var(--rs-cd-line);
  font-family:Poppins,sans-serif;
  font-size:15px;
  font-weight:600;
  color:var(--rs-cd-ink);
}
/* Own footer CTAs only — hide Woo/Elementor "Zobacz koszyk / Zamówienie" in body */
.rs-cart-drawer__body .woocommerce-mini-cart__buttons,
.rs-cart-drawer__body p.woocommerce-mini-cart__buttons,
.rs-cart-drawer__body .buttons,
.rs-cart-drawer__body p.buttons,
.rs-cart-drawer__body .elementor-menu-cart__footer-buttons,
.rs-cart-drawer__body a.button.wc-forward,
.rs-cart-drawer__body a.checkout,
.rs-cart-drawer__body a.elementor-button--view-cart,
.rs-cart-drawer__body a.elementor-button--checkout{
  display:none!important;
}
.rs-cart-drawer__foot{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
  padding:16px 18px 20px;
  border-top:1px solid var(--rs-cd-line);
  background:linear-gradient(180deg,rgba(255,252,250,.88),#FFFCFA 40%);
}
.rs-cart-drawer__foot[hidden]{display:none!important;}
.rs-cart-drawer__btn{
  display:inline-flex;
  align-items:center;
  justify-content:center;
  min-height:48px;
  padding:0 14px;
  border-radius:10px;
  font-family:Poppins,sans-serif;
  font-size:13px;
  font-weight:600;
  text-decoration:none!important;
  letter-spacing:.01em;
  transition:transform .18s ease, background .18s ease, color .18s ease, border-color .18s ease;
}
.rs-cart-drawer__btn:hover{transform:translateY(-1px);}
.rs-cart-drawer__btn--ghost{
  border:1px solid rgba(23,56,62,.22);
  color:var(--rs-cd-forest)!important;
  background:transparent;
}
.rs-cart-drawer__btn--ghost:hover{
  border-color:var(--rs-cd-forest);
  background:rgba(23,56,62,.04);
}
.rs-cart-drawer__btn--solid{
  border:1px solid var(--rs-cd-accent);
  background:var(--rs-cd-accent);
  color:#FFFCFA!important;
}
.rs-cart-drawer__btn--solid:hover{background:var(--rs-cd-accent-deep);border-color:var(--rs-cd-accent-deep);}
body.rs-cart-drawer-lock{overflow:hidden;}
@media (max-width:560px){
  .rs-cart-drawer__panel{width:100vw;}
  .rs-cart-drawer__foot{grid-template-columns:1fr;}
}
</style>';
}, 60);

add_action('wp_enqueue_scripts', static function () {
    if (is_admin() || !function_exists('WC')) {
        return;
    }
    $handle = 'rs-cart-drawer';
    wp_register_script($handle, false, [], '1.0.6', true);
    wp_enqueue_script($handle);

    $js = <<<'JS'
(function () {
  'use strict';
  function boot() {
  var root = document.getElementById('rs-cart-drawer');
  if (!root) return;

  var panel = root.querySelector('.rs-cart-drawer__panel');
  var mount = root.querySelector('[data-rs-cart-mount]');
  var foot = root.querySelector('[data-rs-cart-foot]');
  var lastFocus = null;
  var openTimer = null;

  function cartCount() {
    var el = document.querySelector('.ct-header-cart .ct-cart-content[data-count], .ct-header-cart [data-count]');
    if (el && el.getAttribute('data-count') != null) {
      return parseInt(el.getAttribute('data-count'), 10) || 0;
    }
    var badge = document.querySelector('.ct-header-cart .ct-cart-item .ct-cart-count, .ct-header-cart .ct-cart-count');
    if (badge) {
      var n = parseInt((badge.textContent || '').replace(/\D+/g, ''), 10);
      return isNaN(n) ? 0 : n;
    }
    var items = mount.querySelectorAll('.woocommerce-mini-cart-item, .woocommerce-mini-cart li');
    return items.length;
  }

  function syncFoot() {
    if (!foot) return;
    var empty = !!mount.querySelector('.woocommerce-mini-cart__empty-message');
    var hasItems = !empty && cartCount() > 0;
    if (hasItems) foot.removeAttribute('hidden');
    else foot.setAttribute('hidden', '');
  }

  function polishEmpty() {
    var nodes = mount.querySelectorAll('.woocommerce-mini-cart__empty-message');
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].textContent = 'Tw\u00f3j koszyk jest pusty.';
    }
  }

  function stripDuplicateCtas() {
    var sel = [
      '.woocommerce-mini-cart__buttons',
      'p.buttons',
      '.buttons',
      '.elementor-menu-cart__footer-buttons',
      'a.button.wc-forward',
      'a.checkout',
      'a.elementor-button--view-cart',
      'a.elementor-button--checkout'
    ].join(',');
    var nodes = mount.querySelectorAll(sel);
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].remove();
    }
  }

  function rehome() {
    /* Drawer owns widget_shopping_cart_content (Woo fragments). Only heal if wiped. */
    var host = mount.querySelector('.widget_shopping_cart_content, .ct-cart-content');
    if (!host) {
      mount.innerHTML = '<div class="widget_shopping_cart_content" data-count="0"><div class="woocommerce-mini-cart__empty-message">Twój koszyk jest pusty.</div></div>';
    } else if (!(host.innerHTML || '').trim()) {
      host.innerHTML = '<div class="woocommerce-mini-cart__empty-message">Twój koszyk jest pusty.</div>';
    }
    polishEmpty();
    stripDuplicateCtas();
    syncFoot();
  }

  function isOpen() {
    return root.classList.contains('is-open');
  }

  function openDrawer() {
    rehome();
    polishEmpty();
    stripDuplicateCtas();
    if (isOpen()) return;
    lastFocus = document.activeElement;
    root.classList.add('is-open');
    root.setAttribute('aria-hidden', 'false');
    document.body.classList.add('rs-cart-drawer-lock');
    window.clearTimeout(openTimer);
    openTimer = window.setTimeout(function () {
      try { panel.focus({ preventScroll: true }); } catch (e) { panel.focus(); }
    }, 40);
  }

  function closeDrawer() {
    if (!isOpen()) return;
    root.classList.remove('is-open');
    root.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('rs-cart-drawer-lock');
    if (lastFocus && typeof lastFocus.focus === 'function') {
      try { lastFocus.focus({ preventScroll: true }); } catch (e) {}
    }
  }

  function isCartTrigger(el) {
    if (!el || !el.closest) return null;
    var a = el.closest('a.ct-cart-item, .ct-header-cart > a, .ct-shortcuts-bar [data-id="cart"] a');
    if (!a) return null;
    if (a.closest('#rs-cart-drawer')) return null;
    return a;
  }

  document.addEventListener('click', function (e) {
    var closer = e.target.closest('[data-rs-cart-close]');
    if (closer) {
      e.preventDefault();
      closeDrawer();
      return;
    }
    var trigger = isCartTrigger(e.target);
    if (trigger) {
      e.preventDefault();
      e.stopPropagation();
      openDrawer();
    }
  }, true);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && isOpen()) {
      e.preventDefault();
      closeDrawer();
    }
  });

  if (window.jQuery) {
    var $ = window.jQuery;
    $(document.body).on('added_to_cart wc_fragments_refreshed wc_fragments_loaded removed_from_cart', function () {
      window.setTimeout(function () {
        rehome();
        syncFoot();
      }, 30);
    });
    $(document.body).on('added_to_cart', function () {
      window.setTimeout(openDrawer, 80);
    });
  } else {
    document.body.addEventListener('wc_fragments_refreshed', function () {
      rehome();
    });
  }

  rehome();
  } // boot
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
JS;
    wp_add_inline_script($handle, $js);
}, 40);
