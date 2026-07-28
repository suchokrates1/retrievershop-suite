<?php
/**
 * Plugin Name: Retriever Account SPA
 * Description: AJAX navigation for Woo My Account (no full reload / no jump to hero).
 */
if (!defined('ABSPATH')) {
    exit;
}

add_action('wp_enqueue_scripts', static function () {
    if (!function_exists('is_account_page') || !is_account_page() || is_admin()) {
        return;
    }
    if (!is_user_logged_in()) {
        return;
    }

    $handle = 'rs-account-spa';
    wp_register_script($handle, false, [], '1.0.1', true);
    wp_enqueue_script($handle);

    $myaccount = trailingslashit((string) wc_get_page_permalink('myaccount'));
    $js = <<<'JS'
(function () {
  'use strict';
  var ROOT = document.querySelector('.woocommerce.ct-woo-account, .woocommerce');
  if (!ROOT) return;

  var MYACCOUNT = %MYACCOUNT%;
  var busy = false;

  function panel() {
    return document.querySelector('.woocommerce-MyAccount-content');
  }
  function nav() {
    return document.querySelector('.woocommerce-MyAccount-navigation');
  }

  function ensureAnchor() {
    var p = panel();
    if (!p) return null;
    var host = p.closest('.u-columns, .woocommerce') || p.parentElement;
    if (host && !host.id) {
      host.id = 'rs-account-panel';
    } else if (p && !document.getElementById('rs-account-panel')) {
      p.id = 'rs-account-panel';
    }
    return document.getElementById('rs-account-panel') || p;
  }

  function scrollToPanel() {
    var el = ensureAnchor();
    if (!el) return;
    try {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (e) {
      el.scrollIntoView(true);
    }
  }

  function isAccountUrl(href) {
    if (!href) return false;
    try {
      var u = new URL(href, window.location.href);
      if (u.origin !== window.location.origin) return false;
      var base = new URL(MYACCOUNT, window.location.href);
      if (u.pathname.indexOf(base.pathname) !== 0) return false;
      if (/customer-logout|lost-password/i.test(u.pathname + u.search)) return false;
      return true;
    } catch (e) {
      return false;
    }
  }

  function setActiveNav(url) {
    var n = nav();
    if (!n) return;
    var targetPath = '';
    try { targetPath = new URL(url, window.location.href).pathname.replace(/\/$/, ''); } catch (e) {}
    var best = null, bestLen = -1;
    n.querySelectorAll('li').forEach(function (li) {
      li.classList.remove('is-active');
      var a = li.querySelector('a');
      if (!a) return;
      var path = '';
      try { path = new URL(a.href, window.location.href).pathname.replace(/\/$/, ''); } catch (e2) {}
      if (!path || !targetPath) return;
      if (targetPath === path || targetPath.indexOf(path + '/') === 0) {
        if (path.length > bestLen) { best = li; bestLen = path.length; }
      }
    });
    if (best) best.classList.add('is-active');
  }

  function setLoading(on) {
    var p = panel();
    if (!p) return;
    p.classList.toggle('rs-account-loading', !!on);
    p.setAttribute('aria-busy', on ? 'true' : 'false');
  }

  function swap(html, url, push) {
    var doc = new DOMParser().parseFromString(html, 'text/html');
    var nextContent = doc.querySelector('.woocommerce-MyAccount-content');
    var cur = panel();
    if (!cur || !nextContent) {
      window.location.href = url;
      return;
    }
    cur.innerHTML = nextContent.innerHTML;
    var wel = document.querySelector('.ct-account-welcome');
    var nextWel = doc.querySelector('.ct-account-welcome');
    if (wel && nextWel) {
      wel.innerHTML = nextWel.innerHTML;
    }
    document.body.dispatchEvent(new CustomEvent('rs-account-spa-loaded', { detail: { url: url } }));
    setActiveNav(url);
    if (push) {
      history.pushState({ rsAccountSpa: true, url: url }, '', url);
    }
    setLoading(false);
    scrollToPanel();
  }

  function navigate(url, push) {
    if (busy) return;
    busy = true;
    setLoading(true);
    fetch(url, {
      method: 'GET',
      credentials: 'same-origin',
      headers: { 'X-Requested-With': 'RSAccountSPA', 'Accept': 'text/html' },
      redirect: 'follow'
    }).then(function (res) {
      if (!res.ok) throw new Error('http ' + res.status);
      var finalUrl = res.url || url;
      if (!isAccountUrl(finalUrl)) {
        window.location.href = finalUrl;
        return null;
      }
      return res.text().then(function (html) {
        return { html: html, url: finalUrl };
      });
    }).then(function (payload) {
      if (!payload) return;
      swap(payload.html, payload.url, push !== false);
    }).catch(function () {
      window.location.href = url;
    }).finally(function () {
      busy = false;
    });
  }

  document.addEventListener('click', function (ev) {
    if (ev.defaultPrevented) return;
    if (ev.button !== 0 || ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
    var a = ev.target.closest('a');
    if (!a || !ROOT.contains(a)) return;
    if (a.hasAttribute('download') || a.target === '_blank') return;
    var href = a.getAttribute('href');
    if (!href || href.charAt(0) === '#') return;
    if (!isAccountUrl(href)) return;
    if (a.getAttribute('data-rs-spa') === 'off') return;
    ev.preventDefault();
    navigate(a.href, true);
  }, true);

  window.addEventListener('popstate', function (ev) {
    if (ev.state && ev.state.rsAccountSpa && ev.state.url) {
      navigate(ev.state.url, false);
      return;
    }
    if (isAccountUrl(window.location.href)) {
      navigate(window.location.href, false);
    }
  });

  ensureAnchor();
  if (!history.state || !history.state.rsAccountSpa) {
    history.replaceState({ rsAccountSpa: true, url: window.location.href }, '', window.location.href);
  }
  try {
    var basePath = new URL(MYACCOUNT, window.location.href).pathname.replace(/\/$/, '');
    var curPath = window.location.pathname.replace(/\/$/, '');
    if (curPath !== basePath && curPath.indexOf(basePath + '/') === 0) {
      requestAnimationFrame(function () { scrollToPanel(); });
    }
  } catch (e4) {}
})();
JS;
    $js = str_replace('%MYACCOUNT%', wp_json_encode($myaccount), $js);
    wp_add_inline_script($handle, $js);

    $css = '#rs-account-panel,.woocommerce-MyAccount-content{scroll-margin-top:calc(var(--theme-header-absolute-height, var(--header-height, 110px)) + 16px)}'
        . '.woocommerce-MyAccount-content.rs-account-loading{opacity:.55;pointer-events:none;transition:opacity .15s ease}';
    wp_register_style('rs-account-spa', false, [], '1.0.1');
    wp_enqueue_style('rs-account-spa');
    wp_add_inline_style('rs-account-spa', $css);
}, 40);
