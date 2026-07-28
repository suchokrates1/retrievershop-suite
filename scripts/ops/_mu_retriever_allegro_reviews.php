<?php
/**
 * Plugin Name: Retriever Allegro Reviews
 * Description: Karuzela prawdziwych opinii Allegro na homepage (zamiast sztywnych 3).
 */
if (!defined('ABSPATH')) {
    exit;
}

const RS_REVIEWS_MAGAZYN = 'https://magazyn.retrievershop.pl/api/shop-trust/reviews';

function rs_reviews_fetch(int $limit = 10): array {
    $cache_key = 'rs_allegro_reviews_' . $limit;
    $cached = get_transient($cache_key);
    if (is_array($cached) && !empty($cached['reviews'])) {
        return $cached;
    }
    $resp = wp_remote_get(add_query_arg('limit', $limit, RS_REVIEWS_MAGAZYN), [
        'timeout' => 12,
        'headers' => ['Accept' => 'application/json'],
    ]);
    if (is_wp_error($resp) || (int) wp_remote_retrieve_response_code($resp) !== 200) {
        $fallback = get_option('rs_allegro_reviews_fallback');
        return is_array($fallback) ? $fallback : [];
    }
    $json = json_decode(wp_remote_retrieve_body($resp), true);
    if (!is_array($json) || empty($json['ok']) || empty($json['reviews'])) {
        return [];
    }
    set_transient($cache_key, $json, 2 * HOUR_IN_SECONDS);
    update_option('rs_allegro_reviews_fallback', $json, false);
    return $json;
}

function rs_reviews_format_date(string $iso): string {
    if ($iso === '') {
        return '';
    }
    try {
        $dt = new DateTimeImmutable($iso);
        return $dt->setTimezone(new DateTimeZone('Europe/Warsaw'))->format('d.m.Y');
    } catch (Exception $e) {
        return substr($iso, 0, 10);
    }
}

function rs_reviews_stars_html(float $stars): string {
    $full = (int) floor($stars + 0.01);
    $html = '<span class="rs-rev-card__stars" aria-label="' . esc_attr(number_format($stars, 1, ',', '')) . ' / 5">';
    for ($i = 1; $i <= 5; $i++) {
        $html .= $i <= $full ? '<span class="is-on">★</span>' : '<span class="is-off">★</span>';
    }
    $html .= '</span>';
    return $html;
}

function rs_reviews_card_html(array $r): string {
    $login = esc_html((string) ($r['login'] ?? 'Klient Allegro'));
    $comment = esc_html((string) ($r['comment'] ?? ''));
    $date = esc_html(rs_reviews_format_date((string) ($r['created_at'] ?? '')));
    $stars = (float) ($r['stars'] ?? 5);
    $offer = trim((string) ($r['offer_title'] ?? ''));
    $initial = mb_strtoupper(mb_substr((string) ($r['login'] ?? 'A'), 0, 1));

    $offer_html = $offer !== ''
        ? '<p class="rs-rev-card__offer">' . esc_html($offer) . '</p>'
        : '';

    return '<article class="rs-rev-card">'
        . '<header class="rs-rev-card__head">'
        . '<span class="rs-rev-card__avatar" aria-hidden="true">' . esc_html($initial) . '</span>'
        . '<span class="rs-rev-card__meta">'
        . '<span class="rs-rev-card__name">' . $login . '</span>'
        . ($date !== '' ? '<time class="rs-rev-card__date" datetime="' . esc_attr((string) ($r['created_at'] ?? '')) . '">' . $date . '</time>' : '')
        . '</span>'
        . rs_reviews_stars_html($stars)
        . '</header>'
        . '<p class="rs-rev-card__text">„' . $comment . '”</p>'
        . $offer_html
        . '</article>';
}

function rs_reviews_carousel_html($atts = []): string {
    $atts = shortcode_atts(['limit' => '10'], $atts, 'rs_allegro_reviews');
    $limit = max(4, min(16, (int) $atts['limit']));
    $data = rs_reviews_fetch($limit);
    $reviews = $data['reviews'] ?? [];
    if (count($reviews) < 2) {
        return '';
    }

    $cards = '';
    foreach ($reviews as $r) {
        if (!is_array($r)) {
            continue;
        }
        $cards .= rs_reviews_card_html($r);
    }
    if ($cards === '') {
        return '';
    }

    $profile = esc_url((string) ($data['profile_url'] ?? 'https://allegro.pl/uzytkownik/Retriever_Shop'));
    $uid = 'rs-rev-' . wp_unique_id();

    return '<section class="rs-rev" aria-label="Opinie klientów z Allegro">'
        . '<div class="rs-rev__inner">'
        . '<header class="rs-rev__header">'
        . '<p class="rs-rev__eyebrow">Allegro</p>'
        . '<h2 class="rs-rev__title">Opinie klientów</h2>'
        . '<p class="rs-rev__sub">Prawdziwe oceny kupujących z Allegro — bez scenariusza i stockowych zdjęć.</p>'
        . '</header>'
        . '<div class="rs-rev-rail" data-rs-rev-rail>'
        . '<button type="button" class="rs-rev-rail__nav rs-rev-rail__nav--prev" aria-label="Poprzednie opinie" data-dir="-1">‹</button>'
        . '<div class="rs-rev-rail__viewport">'
        . '<div class="rs-rev-rail__track" id="' . esc_attr($uid) . '">' . $cards . '</div>'
        . '</div>'
        . '<button type="button" class="rs-rev-rail__nav rs-rev-rail__nav--next" aria-label="Następne opinie" data-dir="1">›</button>'
        . '</div>'
        . '<p class="rs-rev__note"><a href="' . $profile . '" rel="noopener noreferrer" target="_blank">Zobacz wszystkie opinie na Allegro →</a></p>'
        . '</div></section>';
}

add_shortcode('rs_allegro_reviews', 'rs_reviews_carousel_html');

/**
 * Safety net: if old avatar testimonials still render inside section d796670,
 * replace ONLY that balanced Elementor <section data-id="d796670">…</section>.
 * Never match until <footer> (that previously ate closing wrappers).
 */
function rs_reviews_replace_balanced_section(string $html, string $sectionId, string $replacement): string {
    $needle = 'data-id="' . $sectionId . '"';
    $pos = strpos($html, $needle);
    if ($pos === false) {
        return $html;
    }
    $start = strrpos(substr($html, 0, $pos + 1), '<section');
    if ($start === false) {
        return $html;
    }

    $len = strlen($html);
    $i = $start;
    $depth = 0;
    while ($i < $len) {
        $open = stripos($html, '<section', $i);
        $close = stripos($html, '</section>', $i);
        if ($close === false) {
            return $html;
        }
        if ($open !== false && $open < $close) {
            $depth++;
            $i = $open + 8;
            continue;
        }
        $depth--;
        $end = $close + strlen('</section>');
        if ($depth === 0) {
            return substr($html, 0, $start) . $replacement . substr($html, $end);
        }
        $i = $end;
    }
    return $html;
}

add_action('template_redirect', static function () {
    if (is_admin() || !is_front_page()) {
        return;
    }
    ob_start(static function ($html) {
        if (!is_string($html) || $html === '') {
            return $html;
        }
        $hasRev = str_contains($html, 'class="rs-rev"');
        $hasOld = str_contains($html, 'user-avatar-1_optimized');
        $brokenJumpToFooter = $hasRev && (bool) preg_match('/class="rs-rev"[\s\S]{0,12000}?<footer\b/i', $html)
            && !str_contains($html, 'data-id="f950bb0"'); // section that should follow Opinie
        // Healthy: shortcode rendered and later Elementor sections still present.
        if ($hasRev && !$hasOld && !$brokenJumpToFooter) {
            return $html;
        }
        if (!$hasOld && !$brokenJumpToFooter && !$hasRev) {
            // No reviews yet and no old block — nothing to do.
            return $html;
        }
        $block = rs_reviews_carousel_html(['limit' => '10']);
        if ($block === '') {
            return $html;
        }
        $wrapped = '<section class="elementor-section elementor-top-section elementor-element elementor-element-d796670 elementor-section-boxed" data-id="d796670" data-element_type="section">'
            . '<div class="elementor-container elementor-column-gap-default"><div class="elementor-column elementor-col-100">'
            . '<div class="elementor-widget-wrap"><div class="elementor-element elementor-widget">'
            . $block
            . '</div></div></div></div></section>';

        if (str_contains($html, 'data-id="d796670"')) {
            return rs_reviews_replace_balanced_section($html, 'd796670', $wrapped);
        }
        // Fallback when section marker was eaten: put carousel back before footer.
        if (str_contains($html, 'class="rs-rev"')) {
            $html = preg_replace('/<section class="rs-rev"[\s\S]*?<\/section>/i', '', $html, 1) ?? $html;
        }
        return preg_replace('/<footer\b/i', $wrapped . '<footer', $html, 1) ?? $html;
    });
}, 1);

add_action('wp_head', static function () {
    if (is_admin() || !is_front_page()) {
        return;
    }
    echo '<style id="rs-rev-css">
.rs-rev{margin:28px auto 40px;max-width:1180px;padding:0 16px;color:var(--rs-ink,#1A3333)}
.rs-rev__header{text-align:center;margin:0 0 22px}
.rs-rev__eyebrow{margin:0 0 6px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--rs-accent,#C45C3E);font-weight:700}
.rs-rev__title{margin:0 0 8px;font-size:clamp(26px,3.4vw,36px);line-height:1.15;font-weight:700}
.rs-rev__sub{margin:0 auto;max-width:560px;font-size:15px;line-height:1.45;color:var(--rs-muted,#5A6B6B)}
.rs-rev-rail{position:relative;display:grid;grid-template-columns:40px 1fr 40px;gap:8px;align-items:center}
.rs-rev-rail__viewport{overflow:hidden}
.rs-rev-rail__track{display:flex;gap:16px;overflow-x:auto;scroll-snap-type:none;scrollbar-width:none;-ms-overflow-style:none;padding:10px 4px 18px;cursor:grab}
.rs-rev-rail__track::-webkit-scrollbar{display:none}
.rs-rev-rail__track.is-dragging{cursor:grabbing}
.rs-rev-rail__track.is-animating{scroll-behavior:auto}
.rs-rev-rail__nav{appearance:none;border:0;width:40px;height:40px;border-radius:999px;background:var(--rs-forest,#17383E);color:var(--rs-on-dark,#FFFCFA);font-size:26px;line-height:1;cursor:pointer;box-shadow:0 8px 20px rgba(26,51,51,.18);transition:transform .2s ease, background .2s ease}
.rs-rev-rail__nav:hover{background:var(--rs-accent,#C45C3E);transform:scale(1.05)}
.rs-rev-card{flex:0 0 calc((100% - 32px)/3);scroll-snap-align:start;background:linear-gradient(180deg,var(--rs-surface,#FFFCFA) 0%,var(--rs-surface-alt,#EEF2F1) 100%);border:1px solid rgba(26,51,51,.06);border-radius:18px;padding:20px 18px 16px;box-shadow:0 14px 34px rgba(26,51,51,.08);min-height:220px;display:flex;flex-direction:column;transition:transform .25s ease, box-shadow .25s ease}
.rs-rev-card:hover{transform:translateY(-3px);box-shadow:0 18px 40px rgba(26,51,51,.12)}
.rs-rev-card__head{display:grid;grid-template-columns:44px 1fr auto;gap:10px;align-items:center;margin-bottom:12px}
.rs-rev-card__avatar{width:44px;height:44px;border-radius:50%;display:grid;place-items:center;background:var(--rs-forest,#17383E);color:var(--rs-on-dark,#FFFCFA);font-weight:700;font-size:18px}
.rs-rev-card__meta{display:flex;flex-direction:column;gap:2px;min-width:0}
.rs-rev-card__name{font-weight:700;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rs-rev-card__date{font-size:12px;color:var(--rs-muted,#5A6B6B)}
.rs-rev-card__stars{color:var(--rs-accent,#C45C3E);font-size:15px;letter-spacing:1px;white-space:nowrap}
.rs-rev-card__stars .is-off{color:#d5cdc3}
.rs-rev-card__text{margin:0;font-size:15px;line-height:1.5;color:var(--rs-ink,#1A3333);flex:1}
.rs-rev-card__offer{margin:12px 0 0;font-size:12px;color:var(--rs-muted,#5A6B6B);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rs-rev__note{margin:6px 0 0;text-align:center;font-size:13px}
.rs-rev__note a{color:var(--rs-accent,#C45C3E);text-decoration:none;font-weight:600}
.rs-rev__note a:hover{text-decoration:underline}
@media (max-width:960px){
  .rs-rev-card{flex-basis:calc((100% - 16px)/2)}
}
@media (max-width:640px){
  .rs-rev-rail{grid-template-columns:1fr}
  .rs-rev-rail__nav{display:none}
  .rs-rev-card{flex-basis:85%}
}
@media (prefers-reduced-motion:reduce){
  .rs-rev-card,.rs-rev-rail__nav{transition:none!important}
}
</style>';
}, 35);

add_action('wp_footer', static function () {
    if (is_admin() || !is_front_page()) {
        return;
    }
    echo '<script id="rs-rev-js">
(function(){
  function stepWidth(track){
    var card=track.querySelector(".rs-rev-card");
    if(!card) return track.clientWidth*0.8;
    var styles=getComputedStyle(track);
    var gap=parseFloat(styles.columnGap||styles.gap)||16;
    return card.getBoundingClientRect().width+gap;
  }
  function maxScroll(track){ return Math.max(0, track.scrollWidth-track.clientWidth); }
  function easeOutQuint(t){ return 1-Math.pow(1-t,5); }
  function animateTo(track,to,ms){
    if(track._rsAnim) cancelAnimationFrame(track._rsAnim);
    var from=track.scrollLeft, dist=to-from;
    if(Math.abs(dist)<0.5) return;
    track.classList.add("is-animating");
    var start=performance.now();
    if(window.matchMedia("(prefers-reduced-motion: reduce)").matches){
      track.scrollLeft=to; track.classList.remove("is-animating"); return;
    }
    function frame(now){
      var p=Math.min(1,(now-start)/ms);
      track.scrollLeft=from+dist*easeOutQuint(p);
      if(p<1) track._rsAnim=requestAnimationFrame(frame);
      else { track._rsAnim=null; track.classList.remove("is-animating"); }
    }
    track._rsAnim=requestAnimationFrame(frame);
  }
  function go(track,dir){
    var step=stepWidth(track), max=maxScroll(track), cur=track.scrollLeft, next=cur+dir*step;
    if(next>max-2) next=(cur>=max-2)?0:max;
    if(next<2 && dir<0) next=(cur<=2)?max:0;
    animateTo(track, Math.max(0,Math.min(next,max)), 760);
  }
  document.querySelectorAll("[data-rs-rev-rail]").forEach(function(rail){
    var track=rail.querySelector(".rs-rev-rail__track");
    if(!track || track.querySelectorAll(".rs-rev-card").length<2) return;
    rail.querySelectorAll(".rs-rev-rail__nav").forEach(function(btn){
      btn.addEventListener("click", function(e){
        e.preventDefault();
        go(track, parseInt(btn.getAttribute("data-dir")||"1",10));
        restart();
      });
    });
    var timer=null, paused=false;
    function tick(){ if(!paused) go(track,1); }
    function restart(){ if(timer) clearInterval(timer); timer=setInterval(tick,5200); }
    function pause(){ paused=true; }
    function resume(){ paused=false; }
    rail.addEventListener("mouseenter", pause);
    rail.addEventListener("mouseleave", resume);
    track.addEventListener("touchstart", pause, {passive:true});
    track.addEventListener("touchend", function(){ setTimeout(resume,2600); }, {passive:true});
    var down=false,startX=0,startLeft=0,moved=false;
    track.addEventListener("pointerdown", function(e){
      if(e.pointerType==="mouse" && e.button!==0) return;
      if(track._rsAnim){ cancelAnimationFrame(track._rsAnim); track._rsAnim=null; track.classList.remove("is-animating"); }
      down=true; moved=false; startX=e.clientX; startLeft=track.scrollLeft;
      track.classList.add("is-dragging");
      try{ track.setPointerCapture(e.pointerId);}catch(_e){}
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
      down=false; track.classList.remove("is-dragging");
      if(moved){
        var step=stepWidth(track);
        var target=Math.round(track.scrollLeft/step)*step;
        animateTo(track, Math.max(0,Math.min(target,maxScroll(track))), 500);
      }
      setTimeout(resume,2000);
    }
    track.addEventListener("pointerup", endDrag);
    track.addEventListener("pointercancel", endDrag);
    if(!window.matchMedia("(prefers-reduced-motion: reduce)").matches) restart();
  });
})();
</script>';
}, 45);
