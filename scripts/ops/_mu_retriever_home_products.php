<?php
/**
 * Plugin Name: Retriever Home Products
 * Description: Bestsellery i Nowości z magazynu — karuzela z peek i płynną animacją.
 */
if (!defined('ABSPATH')) {
    exit;
}

const RS_HOME_MAGAZYN_BASE = 'https://magazyn.retrievershop.pl';

function rs_home_fetch_json(string $path): ?array {
    $cache_key = 'rs_home_' . md5($path);
    $cached = get_transient($cache_key);
    if (is_array($cached)) {
        return $cached;
    }
    $url = rtrim(RS_HOME_MAGAZYN_BASE, '/') . $path;
    $resp = wp_remote_get($url, [
        'timeout' => 10,
        'headers' => ['Accept' => 'application/json'],
    ]);
    if (is_wp_error($resp) || (int) wp_remote_retrieve_response_code($resp) !== 200) {
        return null;
    }
    $json = json_decode(wp_remote_retrieve_body($resp), true);
    if (!is_array($json) || empty($json['ok'])) {
        return null;
    }
    set_transient($cache_key, $json, 30 * MINUTE_IN_SECONDS);
    return $json;
}

/** @return list<WC_Product> */
function rs_home_resolve_products(array $items, int $limit = 12): array {
    $out = [];
    $seen = [];
    foreach ($items as $item) {
        $wid = (int) ($item['woo_product_id'] ?? 0);
        if ($wid < 1 || isset($seen[$wid])) {
            continue;
        }
        $p = wc_get_product($wid);
        if (!$p || $p->get_status() !== 'publish') {
            continue;
        }
        if (!$p->is_in_stock() || !$p->get_image_id()) {
            continue;
        }
        if ($p->get_catalog_visibility() === 'hidden') {
            continue;
        }
        $seen[$wid] = true;
        $out[] = $p;
        if (count($out) >= $limit) {
            break;
        }
    }
    return $out;
}

function rs_home_card_html(WC_Product $p): string {
    $url = esc_url(get_permalink($p->get_id()));
    $name = esc_html($p->get_name());
    $img = $p->get_image('woocommerce_thumbnail', [
        'class' => 'rs-home-card__img',
        'loading' => 'lazy',
        'alt' => $p->get_name(),
    ]);
    // Woo already prefixes variable prices with "od" — don't add a second one.
    $price = $p->get_price_html();
    return '<a class="rs-home-card" href="' . $url . '">'
        . '<span class="rs-home-card__media">' . $img . '</span>'
        . '<span class="rs-home-card__body">'
        . '<span class="rs-home-card__title">' . $name . '</span>'
        . '<span class="rs-home-card__price">' . $price . '</span>'
        . '</span></a>';
}

function rs_home_rail_html(array $products, string $label): string {
    if (!$products) {
        return '';
    }
    $cards = '';
    foreach ($products as $p) {
        $cards .= rs_home_card_html($p);
    }
    $uid = 'rs-rail-' . wp_unique_id();
    return '<div class="rs-home-rail" data-rs-rail aria-label="' . esc_attr($label) . '">'
        . '<button type="button" class="rs-home-rail__nav rs-home-rail__nav--prev" aria-label="Poprzednie" data-dir="-1">‹</button>'
        . '<div class="rs-home-rail__viewport">'
        . '<div class="rs-home-rail__track" id="' . esc_attr($uid) . '">' . $cards . '</div>'
        . '</div>'
        . '<button type="button" class="rs-home-rail__nav rs-home-rail__nav--next" aria-label="Następne" data-dir="1">›</button>'
        . '</div>';
}

function rs_home_bestsellers_html($atts = []): string {
    $atts = shortcode_atts(['limit' => '10', 'days' => '90'], $atts, 'rs_bestsellers');
    $limit = max(6, min(16, (int) $atts['limit']));
    $days = max(30, min(180, (int) $atts['days']));
    $data = rs_home_fetch_json('/api/shop-trust/bestsellers?limit=' . ($limit + 8) . '&days=' . $days);
    $items = is_array($data) ? ($data['items'] ?? []) : [];
    $products = rs_home_resolve_products($items, $limit);
    if (count($products) < $limit) {
        $ids = wc_get_products([
            'status' => 'publish',
            'limit' => $limit,
            'orderby' => 'popularity',
            'stock_status' => 'instock',
            'return' => 'ids',
        ]);
        $seen = array_map(static fn($p) => $p->get_id(), $products);
        foreach ($ids as $id) {
            if (in_array($id, $seen, true)) {
                continue;
            }
            $p = wc_get_product($id);
            if ($p && $p->get_image_id()) {
                $products[] = $p;
            }
            if (count($products) >= $limit) {
                break;
            }
        }
    }
    return rs_home_rail_html($products, 'Bestsellery');
}

function rs_home_new_delivery_html($atts = []): string {
    $atts = shortcode_atts(['limit' => '12'], $atts, 'rs_new_delivery');
    $limit = max(8, min(16, (int) $atts['limit']));
    $data = rs_home_fetch_json('/api/shop-trust/latest-delivery?limit=' . ($limit + 8));
    $items = is_array($data) ? ($data['items'] ?? []) : [];
    $products = rs_home_resolve_products($items, $limit);
    if (count($products) < $limit) {
        $ids = wc_get_products([
            'status' => 'publish',
            'limit' => $limit * 2,
            'orderby' => 'date',
            'order' => 'DESC',
            'stock_status' => 'instock',
            'return' => 'ids',
        ]);
        $seen = array_map(static fn($p) => $p->get_id(), $products);
        foreach ($ids as $id) {
            if (in_array($id, $seen, true)) {
                continue;
            }
            $p = wc_get_product($id);
            if ($p && $p->get_image_id() && $p->get_catalog_visibility() !== 'hidden') {
                $products[] = $p;
            }
            if (count($products) >= $limit) {
                break;
            }
        }
    }
    return rs_home_rail_html($products, 'Nowości');
}

add_shortcode('rs_bestsellers', 'rs_home_bestsellers_html');
add_shortcode('rs_new_delivery', 'rs_home_new_delivery_html');
add_shortcode('rs_nowosci', 'rs_home_new_delivery_html');

add_action('wp_head', static function () {
    if (is_admin()) {
        return;
    }
    echo '<style id="rs-home-rail">
.rs-home-rail{--rs-gap:14px;--rs-slots:5;position:relative;max-width:100%;width:100%;margin:4px auto 18px;padding:0}
.rs-home-rail__viewport{position:relative;overflow:hidden;mask-image:linear-gradient(90deg,transparent 0, #000 2.5%, #000 97.5%, transparent 100%);-webkit-mask-image:linear-gradient(90deg,transparent 0,#000 2.5%,#000 97.5%,transparent 100%)}
.rs-home-rail__track{display:grid;grid-auto-flow:column;grid-auto-columns:calc((100% - (var(--rs-gap) * var(--rs-slots))) / var(--rs-slots));gap:var(--rs-gap);overflow-x:auto;scroll-snap-type:none;scrollbar-width:none;-ms-overflow-style:none;padding:10px 0 18px;cursor:grab;-webkit-overflow-scrolling:touch}
.rs-home-rail__track::-webkit-scrollbar{display:none}
.rs-home-rail__track.is-dragging,.rs-home-rail__track.is-animating{cursor:grabbing;scroll-snap-type:none!important;scroll-behavior:auto!important}
.rs-home-card{display:flex;flex-direction:column;text-decoration:none;color:inherit;background:#fff;border:1px solid rgba(26,51,51,.08);border-radius:14px;overflow:hidden;min-height:0;box-shadow:0 1px 0 rgba(26,51,51,.03),0 8px 24px rgba(26,51,51,.06);transition:transform .45s cubic-bezier(.22,1,.36,1),box-shadow .45s cubic-bezier(.22,1,.36,1)}
.rs-home-card:hover{transform:translateY(-4px);box-shadow:0 10px 28px rgba(26,51,51,.12)}
.rs-home-card__media{display:block;aspect-ratio:1/1;background:var(--rs-surface-alt,#EEF2F1);overflow:hidden;position:relative}
.rs-home-card__media::after{content:"";position:absolute;inset:auto 0 0 0;height:28%;background:linear-gradient(180deg,transparent,rgba(26,51,51,.04));pointer-events:none}
.rs-home-card__media img,.rs-home-card__img{width:100%!important;height:100%!important;object-fit:cover!important;margin:0!important;display:block;transform:scale(1.01);transition:transform .7s cubic-bezier(.22,1,.36,1)}
.rs-home-card:hover .rs-home-card__img{transform:scale(1.06)}
.rs-home-card__body{display:flex;flex-direction:column;gap:6px;padding:12px 12px 14px;min-height:84px;background:linear-gradient(180deg,#fff 0%,#fcfaf7 100%)}
.rs-home-card__title{font-size:13.5px;line-height:1.3;font-weight:600;letter-spacing:-.01em;color:var(--rs-ink,#1A3333);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;min-height:2.6em}
.rs-home-card__price{font-size:15px;font-weight:700;color:var(--rs-accent,#C45C3E);display:flex;align-items:baseline;gap:4px;flex-wrap:wrap}
.rs-home-card__price .amount{color:var(--rs-accent,#C45C3E)}
.rs-home-card__price del{opacity:.45;font-weight:500;margin-right:2px;font-size:13px}
.rs-home-card__price ins{text-decoration:none}
.rs-home-rail__nav{position:absolute;top:44%;transform:translateY(-50%);z-index:3;width:36px;height:36px;border:0;border-radius:999px;background:rgba(26,51,51,.92);color:#fff;font-size:22px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;opacity:0;transition:opacity .25s ease,transform .25s ease,background .2s ease;box-shadow:0 6px 16px rgba(0,0,0,.16)}
.rs-home-rail:hover .rs-home-rail__nav,.rs-home-rail:focus-within .rs-home-rail__nav{opacity:.95}
.rs-home-rail__nav:hover{background:var(--rs-forest,#17383E);transform:translateY(-50%) scale(1.05)}
.rs-home-rail__nav--prev{left:2px}
.rs-home-rail__nav--next{right:2px}
@media (max-width:900px){
  .rs-home-rail{--rs-slots:3;--rs-gap:12px}
  .rs-home-rail__nav{opacity:.85}
}
@media (max-width:520px){
  .rs-home-rail{--rs-slots:2.2;--rs-gap:10px;padding:0}
  .rs-home-card{border-radius:12px}
  .rs-home-card__body{min-height:76px;padding:10px}
  .rs-home-card__title{font-size:12.5px}
  .rs-home-rail__nav{display:none}
}
@media (prefers-reduced-motion:reduce){
  .rs-home-card,.rs-home-card__img,.rs-home-rail__nav{transition:none!important}
}
</style>';
}, 30);

add_action('wp_footer', static function () {
    if (is_admin()) {
        return;
    }
    echo '<script id="rs-home-rail-js">
(function(){
  function stepWidth(track){
    var card=track.querySelector(".rs-home-card");
    if(!card) return track.clientWidth*0.8;
    var styles=getComputedStyle(track);
    var gap=parseFloat(styles.columnGap||styles.gap)||14;
    return card.getBoundingClientRect().width+gap;
  }
  function maxScroll(track){ return Math.max(0, track.scrollWidth-track.clientWidth); }
  function easeOutQuint(t){ return 1-Math.pow(1-t,5); }
  function animateTo(track, to, ms){
    if(track._rsAnim) cancelAnimationFrame(track._rsAnim);
    var from=track.scrollLeft;
    var dist=to-from;
    if(Math.abs(dist)<0.5) return;
    track.classList.add("is-animating");
    var start=performance.now();
    var reduced=window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if(reduced){ track.scrollLeft=to; track.classList.remove("is-animating"); return; }
    function frame(now){
      var p=Math.min(1,(now-start)/ms);
      track.scrollLeft=from+dist*easeOutQuint(p);
      if(p<1){ track._rsAnim=requestAnimationFrame(frame); }
      else { track._rsAnim=null; track.classList.remove("is-animating"); }
    }
    track._rsAnim=requestAnimationFrame(frame);
  }
  function go(track, dir){
    var step=stepWidth(track);
    var max=maxScroll(track);
    var cur=track.scrollLeft;
    var next=cur+dir*step;
    // Bounce/loop with the same easing (no instant jump)
    if(next>max-2){ next = (cur>=max-2) ? 0 : max; }
    if(next<2 && dir<0){ next = (cur<=2) ? max : 0; }
    next=Math.max(0, Math.min(next, max));
    animateTo(track, next, 780);
  }
  document.querySelectorAll("[data-rs-rail]").forEach(function(rail){
    var track=rail.querySelector(".rs-home-rail__track");
    if(!track) return;
    if(track.querySelectorAll(".rs-home-card").length<2) return;

    function alignPeek(){
      var card=track.querySelector(".rs-home-card");
      if(!card) return;
      track.scrollLeft=Math.min(card.getBoundingClientRect().width*0.5, maxScroll(track));
    }
    alignPeek();
    var resizeTimer;
    window.addEventListener("resize", function(){
      clearTimeout(resizeTimer);
      resizeTimer=setTimeout(alignPeek, 120);
    }, {passive:true});

    rail.querySelectorAll(".rs-home-rail__nav").forEach(function(btn){
      btn.addEventListener("click", function(e){
        e.preventDefault();
        go(track, parseInt(btn.getAttribute("data-dir")||"1",10));
        restart();
      });
    });

    var timer=null, paused=false;
    function tick(){ if(!paused) go(track, 1); }
    function restart(){
      if(timer) clearInterval(timer);
      timer=setInterval(tick, 4800);
    }
    function pause(){ paused=true; }
    function resume(){ paused=false; }
    rail.addEventListener("mouseenter", pause);
    rail.addEventListener("mouseleave", resume);
    rail.addEventListener("focusin", pause);
    rail.addEventListener("focusout", resume);
    track.addEventListener("touchstart", pause, {passive:true});
    track.addEventListener("touchend", function(){ setTimeout(resume, 2800); }, {passive:true});

    var down=false, startX=0, startLeft=0, moved=false;
    track.addEventListener("pointerdown", function(e){
      if(e.pointerType==="mouse" && e.button!==0) return;
      if(track._rsAnim){ cancelAnimationFrame(track._rsAnim); track._rsAnim=null; track.classList.remove("is-animating"); }
      down=true; moved=false; startX=e.clientX; startLeft=track.scrollLeft;
      track.classList.add("is-dragging");
      try{ track.setPointerCapture(e.pointerId); }catch(_e){}
      pause();
    });
    track.addEventListener("pointermove", function(e){
      if(!down) return;
      var dx=e.clientX-startX;
      if(Math.abs(dx)>4) moved=true;
      track.scrollLeft=startLeft-dx;
    });
    function endDrag(){
      if(!down) return;
      down=false;
      track.classList.remove("is-dragging");
      if(moved){
        var step=stepWidth(track);
        var target=Math.round(track.scrollLeft/step)*step;
        animateTo(track, Math.max(0, Math.min(target, maxScroll(track))), 520);
      }
      setTimeout(resume, 2200);
    }
    track.addEventListener("pointerup", endDrag);
    track.addEventListener("pointercancel", endDrag);
    track.addEventListener("click", function(e){
      if(moved){ e.preventDefault(); e.stopPropagation(); }
    }, true);

    if(!window.matchMedia("(prefers-reduced-motion: reduce)").matches) restart();
  });
})();
</script>';
}, 40);
