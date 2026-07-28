<?php
/**
 * Plugin Name: Retriever UI backgrounds
 * Description: Forest+Coral design tokens, section rhythm, paw heroes, promo contrast.
 */
if (!defined('ABSPATH')) {
    exit;
}

add_action('wp_head', static function () {
    if (is_admin()) {
        return;
    }
    $paw = 'https://retrievershop.pl/wp-content/uploads/2024/08/paw-pattern-2.svg';
    echo '<style id="rs-ui-bg">
:root{
  --rs-forest:#17383E;
  --rs-ink:#1A3333;
  --rs-muted:#5A6B6B;
  --rs-surface:#FFFCFA;
  --rs-surface-alt:#EEF2F1;
  --rs-accent:#C45C3E;
  --rs-accent-deep:#9E4A32;
  --rs-on-dark:#FFFCFA;
  --rs-on-accent:#FFFCFA;
  --rs-sand:var(--rs-surface-alt);
  --rs-cream:var(--rs-surface-alt);
  /* Unified hero tokens — Kontakt (text) / O nas (photo). Home excluded.
     Sticky header ≈166px; Kontakt clearance title↔sticky ≈110px → titleTop ≈276. */
  --rs-hero-title-size:70px;
  --rs-hero-title-weight:700;
  --rs-hero-title-font:Poppins,sans-serif;
  --rs-hero-text-min-h:400px;
  --rs-hero-pad-top:276px;
  --rs-hero-pad-bottom:48px;
  --rs-hero-photo-img-max:320px;
  /* Blocksy title strip + Elementor dog are separate; this is dog pad-top only.
     Empirically pad-top + ~72px chrome = visual gap; 38 → ≈110 like O nas. */
  --rs-hero-title-to-photo:38px;
}
@media (max-width:782px){
  :root{
    --rs-hero-title-size:clamp(2rem,8vw,2.75rem);
    --rs-hero-text-min-h:300px;
    --rs-hero-pad-top:160px;
  }
}

/* ========== Unified heroes (except homepage) ========== */
/* TEXT heroes — every Blocksy type-2 page (shop, PDP, blog, archives, pages…) */
body:not(.home):not(.front-page) .hero-section[data-type="type-2"]{
  background-color:var(--rs-forest)!important;
  background-image:url("' . esc_url($paw) . '")!important;
  background-size:cover!important;
  background-position:center!important;
  background-repeat:no-repeat!important;
  min-height:var(--rs-hero-text-min-h)!important;
  margin-top:0!important;
  padding-top:var(--rs-hero-pad-top)!important;
  padding-bottom:var(--rs-hero-pad-bottom)!important;
  display:flex!important;
  align-items:center!important;
  justify-content:center!important;
}
/* PHOTO pages (Koszyk/Kasa/Konto): compact title strip — photo gap like O nas */
body.woocommerce-cart .hero-section[data-type="type-2"],
body.page-id-1977 .hero-section[data-type="type-2"],
body.woocommerce-checkout .hero-section[data-type="type-2"],
body.page-id-1978 .hero-section[data-type="type-2"],
body.woocommerce-account .hero-section[data-type="type-2"],
body.page-id-1979 .hero-section[data-type="type-2"]{
  background-color:var(--rs-forest)!important;
  background-image:url("' . esc_url($paw) . '")!important;
  background-size:cover!important;
  background-position:center!important;
  background-repeat:no-repeat!important;
  min-height:0!important;
  height:auto!important;
  margin-top:0!important;
  padding-top:var(--rs-hero-pad-top)!important;
  padding-bottom:0!important;
  display:flex!important;
  align-items:flex-end!important;
  justify-content:center!important;
}
/* Blocksy packs title in .entry-header with min-height:250 + pad 50 — kill that */
body:not(.home):not(.front-page) .hero-section[data-type="type-2"] .entry-header{
  min-height:0!important;
  height:auto!important;
  padding:0!important;
  margin:0!important;
  display:block!important;
  width:100%!important;
}
body:not(.home):not(.front-page) .hero-section[data-type="type-2"] .page-title{
  display:block!important;
  color:var(--rs-on-dark)!important;
  font-family:var(--rs-hero-title-font)!important;
  font-size:var(--rs-hero-title-size)!important;
  font-weight:var(--rs-hero-title-weight)!important;
  line-height:1.15!important;
  margin:0!important;
  text-align:center!important;
}
/* Unify: no breadcrumbs in any hero */
body:not(.home):not(.front-page) .hero-section .ct-breadcrumbs,
body:not(.home):not(.front-page) .hero-section .woocommerce-breadcrumb{
  display:none!important;
}
/* Flush under sticky header — no pull-up; pad-top handles clearance like Kontakt */
body:not(.home):not(.front-page) #main{
  padding-top:0!important;
  margin-top:0!important;
}
body:not(.home):not(.front-page) #header{
  margin-bottom:0!important;
}
body:not(.home):not(.front-page) #main>.hero-section[data-type="type-2"]{
  margin-top:0!important;
}
/* Blog page: never show featured photo in hero — forest + paws like other pages */
body.blog .hero-section figure,
body.blog .hero-section .ct-media-container,
body.blog .hero-section .ct-image-container,
body.page-id-5913 .hero-section figure,
body.page-id-5913 .hero-section .ct-media-container,
body.page-id-5913 .hero-section .ct-image-container,
body.page-slug-blog .hero-section figure,
body.page-slug-blog .hero-section .ct-media-container{
  display:none!important;
}
/* Hero subtitle/excerpt — light on forest (was inheriting dark ink) */
body.woocommerce-shop .hero-section[data-type="type-2"] .page-description,
body.woocommerce-shop .hero-section[data-type="type-2"] .page-description p,
body.page-id-1976 .hero-section[data-type="type-2"] .page-description,
body.page-id-1976 .hero-section[data-type="type-2"] .page-description p,
body.blog .hero-section[data-type="type-2"] .page-description,
body.blog .hero-section[data-type="type-2"] .page-description p,
body.single-post .hero-section[data-type="type-2"] .page-description,
body.single-post .hero-section[data-type="type-2"] .page-description p,
body.page-id-5913 .hero-section[data-type="type-2"] .page-description,
body.page-id-5913 .hero-section[data-type="type-2"] .page-description p{
  color:rgba(255,252,250,.88)!important;
}
body.woocommerce-shop .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.page-id-1976 .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.woocommerce-shop .hero-section[data-type="type-2"] .ct-breadcrumbs a,
body.blog .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.blog .hero-section[data-type="type-2"] .ct-breadcrumbs a,
body.single-post .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.single-post .hero-section[data-type="type-2"] .ct-breadcrumbs a,
body.page-id-5913 .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.page-id-5913 .hero-section[data-type="type-2"] .ct-breadcrumbs a,
body.woocommerce-cart .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.woocommerce-cart .hero-section[data-type="type-2"] .ct-breadcrumbs a,
body.page-id-1977 .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.page-id-1977 .hero-section[data-type="type-2"] .ct-breadcrumbs a,
body.woocommerce-checkout .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.woocommerce-checkout .hero-section[data-type="type-2"] .ct-breadcrumbs a,
body.page-id-1978 .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.page-id-1978 .hero-section[data-type="type-2"] .ct-breadcrumbs a,
body.woocommerce-account .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.woocommerce-account .hero-section[data-type="type-2"] .ct-breadcrumbs a,
body.page-id-1979 .hero-section[data-type="type-2"] .ct-breadcrumbs,
body.page-id-1979 .hero-section[data-type="type-2"] .ct-breadcrumbs a{
  color:rgba(255,252,250,.85)!important;
}

/* O nas = photo-hero reference: only lock title tokens (do not shrink its photo) */
body.page-id-1037 .elementor-element-cab6238 .elementor-heading-title,
body.page-id-1037 .elementor-element-cab6238 h1{
  font-family:var(--rs-hero-title-font)!important;
  font-size:var(--rs-hero-title-size)!important;
  font-weight:var(--rs-hero-title-weight)!important;
  line-height:1.15!important;
  color:var(--rs-on-dark)!important;
}
/* Kontakt — text hero reference: pad keeps H1 ≈276 (eyebrow sits above) */
body.page-id-1361 .elementor-element-cb5db08{
  --padding-top:220px!important;
  --padding-bottom:48px!important;
  min-height:var(--rs-hero-text-min-h)!important;
  padding-top:220px!important;
  padding-bottom:var(--rs-hero-pad-bottom)!important;
  display:flex!important;
  align-items:center!important;
  justify-content:center!important;
}
body.page-id-1361 .elementor-element-cb5db08 .elementor-heading-title,
body.page-id-1361 .elementor-element-cb5db08 h1{
  font-family:var(--rs-hero-title-font)!important;
  font-size:var(--rs-hero-title-size)!important;
  font-weight:var(--rs-hero-title-weight)!important;
  line-height:1.15!important;
  color:var(--rs-on-dark)!important;
  text-align:center!important;
  margin:0!important;
}
/* Koszyk / Kasa / Konto — dog band: title→photo ≈ O nas (~110px), no tall empty flex */
body.page-id-1977 .elementor-element-effbd38,
body.woocommerce-cart .elementor-element-effbd38,
body.page-id-1978 .elementor-element-b77a55d,
body.woocommerce-checkout .elementor-element-b77a55d,
body.page-id-1979 .elementor-element-31489c0,
body.woocommerce-account .elementor-element-31489c0{
  background-color:var(--rs-forest)!important;
  margin-top:0!important;
  padding-top:var(--rs-hero-title-to-photo)!important;
  padding-bottom:48px!important;
  min-height:0!important;
  height:auto!important;
  --min-height:0px!important;
  justify-content:flex-start!important;
  align-items:center!important;
  overflow:visible!important;
}
body.page-id-1977 .elementor-element-effbd38 > .e-con-inner,
body.woocommerce-cart .elementor-element-effbd38 > .e-con-inner,
body.page-id-1978 .elementor-element-b77a55d > .e-con-inner,
body.woocommerce-checkout .elementor-element-b77a55d > .e-con-inner,
body.page-id-1979 .elementor-element-31489c0 > .e-con-inner,
body.woocommerce-account .elementor-element-31489c0 > .e-con-inner{
  min-height:0!important;
  height:auto!important;
  --min-height:0px!important;
  justify-content:flex-start!important;
  align-items:center!important;
  padding-top:0!important;
  padding-bottom:0!important;
}
body.page-id-1977 .elementor-element-effbd38::before,
body.woocommerce-cart .elementor-element-effbd38::before,
body.page-id-1978 .elementor-element-b77a55d::before,
body.woocommerce-checkout .elementor-element-b77a55d::before,
body.page-id-1979 .elementor-element-31489c0::before,
body.woocommerce-account .elementor-element-31489c0::before{
  background-image:url("' . esc_url($paw) . '")!important;
  background-size:cover!important;
  opacity:.6!important;
}
body.page-id-1977 .elementor-element-effbd38 img,
body.woocommerce-cart .elementor-element-effbd38 img,
body.page-id-1978 .elementor-element-b77a55d img,
body.woocommerce-checkout .elementor-element-b77a55d img,
body.page-id-1979 .elementor-element-rsaccimg img,
body.woocommerce-account .elementor-element-rsaccimg img{
  display:block!important;
  max-height:var(--rs-hero-photo-img-max)!important;
  width:auto!important;
  max-width:min(420px,70vw)!important;
  height:auto!important;
  object-fit:contain!important;
  margin:0 auto!important;
}
body.page-id-1977 .elementor-element-effbd38 .elementor-widget-image .elementor-widget-container,
body.woocommerce-cart .elementor-element-effbd38 .elementor-widget-image .elementor-widget-container,
body.page-id-1978 .elementor-element-b77a55d .elementor-widget-image .elementor-widget-container,
body.woocommerce-checkout .elementor-element-b77a55d .elementor-widget-image .elementor-widget-container,
body.page-id-1979 .elementor-element-rsaccimg > .elementor-widget-container,
body.woocommerce-account .elementor-element-rsaccimg > .elementor-widget-container{
  margin:0 auto!important;
  max-width:min(420px,70vw);
}
/* Hide duplicate Elementor H2 under photo heroes (Blocksy title is enough) */
body.page-id-1977 .elementor-element-14550bb,
body.woocommerce-cart .elementor-element-14550bb{
  display:none!important;
}
body.page-id-1979 .elementor-element-304eff9f,
body.woocommerce-account .elementor-element-304eff9f{
  padding-top:16px!important;
}
/* Login/register fields — stronger contrast */
body.woocommerce-account .woocommerce-form input.input-text,
body.woocommerce-account .woocommerce-form input[type="text"],
body.woocommerce-account .woocommerce-form input[type="email"],
body.woocommerce-account .woocommerce-form input[type="password"],
body.woocommerce-account .woocommerce-Input{
  border:1px solid rgba(23,56,62,.22)!important;
  background:#fff!important;
  min-height:44px;
  color:var(--rs-ink,#1A3333)!important;
}
body.woocommerce-account .woocommerce-form label br{
  display:none!important;
}
body.woocommerce-account .u-columns.col2-set{
  display:grid!important;
  grid-template-columns:1fr 1fr;
  gap:32px;
  align-items:start;
}
@media (max-width:782px){
  body.woocommerce-account .u-columns.col2-set{
    grid-template-columns:1fr;
  }
}

/* Moje konto — nav: keep Blocksy icon+label on one row */
body.woocommerce-account .ct-account-welcome{
  display:flex;
  align-items:center;
  gap:12px;
  margin:0 0 14px;
  padding:14px 16px;
  border:1px solid rgba(23,56,62,.12);
  border-radius:12px;
  background:var(--rs-surface,#FFFCFA);
}
body.woocommerce-account .ct-account-welcome .ct-account-user-box{
  display:flex;
  flex-direction:column;
  gap:2px;
  min-width:0;
}
body.woocommerce-account .woocommerce-MyAccount-navigation ul{
  list-style:none;
  margin:0 0 1.5rem;
  padding:0;
  border:1px solid rgba(23,56,62,.12);
  border-radius:12px;
  overflow:hidden;
  background:var(--rs-surface,#FFFCFA);
}
body.woocommerce-account .woocommerce-MyAccount-navigation li{
  margin:0;
}
body.woocommerce-account .woocommerce-MyAccount-navigation a{
  display:flex!important;
  flex-direction:row!important;
  align-items:center!important;
  gap:0;
  height:auto!important;
  min-height:48px;
  padding:10px 16px!important;
  color:var(--rs-ink,#1A3333)!important;
  text-decoration:none;
  font-weight:500;
  line-height:1.25;
}
body.woocommerce-account .woocommerce-MyAccount-navigation a:before{
  display:inline-block!important;
  flex:0 0 20px;
  width:20px!important;
  margin-inline-end:12px!important;
  text-align:center;
  line-height:1;
}
body.woocommerce-account .woocommerce-MyAccount-navigation li.is-active a,
body.woocommerce-account .woocommerce-MyAccount-navigation a:hover{
  background:var(--rs-surface-alt,#EEF2F1);
  color:var(--rs-forest,#17383E)!important;
}
body.woocommerce-account .woocommerce-MyAccount-content{
  color:var(--rs-ink,#1A3333);
}
body.woocommerce-account .woocommerce-button,
body.woocommerce-account .button,
body.woocommerce-account button.button{
  background:var(--rs-accent,#C45C3E)!important;
  color:var(--rs-on-accent,#FFFCFA)!important;
  border-color:var(--rs-accent,#C45C3E)!important;
}
body.woocommerce-account .woocommerce-button:hover,
body.woocommerce-account .button:hover,
body.woocommerce-account button.button:hover{
  background:var(--rs-accent-deep,#9E4A32)!important;
  border-color:var(--rs-accent-deep,#9E4A32)!important;
}

/* Header account dropdown — icon/text inline */
.ct-header-account-dropdown .menu-item > a.ct-menu-link,
.ct-header-account-dropdown .menu-item > .ct-menu-link{
  display:flex!important;
  flex-direction:row!important;
  align-items:center!important;
  gap:10px;
}
.ct-header-account-dropdown .menu-item > a.ct-menu-link .ct-icon,
.ct-header-account-dropdown .menu-item > a.ct-menu-link svg{
  flex:0 0 auto;
}

/* Mini-cart UI lives in retriever-cart-drawer.php (right drawer). */

/* O Nas: ensure Elementor hero keeps local paw even if CSS cache stale */
body.page-id-1037 .elementor-section.elementor-top-section:first-of-type,
body.page-id-1037 .elementor-top-section:first-child,
body.page-id-1037 .elementor-element-cab6238{
  background-color:var(--rs-forest)!important;
  background-image:url("' . esc_url($paw) . '")!important;
  background-size:cover!important;
  background-position:center!important;
}

/* O nas — section rhythm (surface / surface-alt) */
body.page-id-1037 .elementor-element-eb00143,
body.page-id-1037 .elementor-element-a295853,
body.page-id-1037 .elementor-element-983ba8c,
body.page-id-1037 .elementor-element-5a3c136{
  background-color:var(--rs-surface)!important;
}
body.page-id-1037 .elementor-element-c6c54f6,
body.page-id-1037 .elementor-element-3924a0d,
body.page-id-1037 .elementor-element-ba38bcd,
body.page-id-1037 .elementor-element-d616e5b{
  background-color:var(--rs-surface-alt)!important;
}

/* Kontakt — hero + section rhythm + forest newsletter */
body.page-id-1361 .elementor-element-cb5db08{
  background-color:var(--rs-forest)!important;
  background-image:url("' . esc_url($paw) . '")!important;
  background-size:cover!important;
  background-position:center!important;
}
/* Contact cards row (moved out of forest hero) — light cards, dark text */
body.page-id-1361 .elementor-element-rskontact{
  background-color:var(--rs-surface)!important;
  padding-top:40px!important;
  padding-bottom:56px!important;
}
body.page-id-1361 .elementor-element-e550d95 > .elementor-container{
  gap:18px;
  align-items:stretch;
}
body.page-id-1361 .elementor-element-e550d95 > .elementor-container > .elementor-column > .elementor-widget-wrap{
  background:#fff!important;
  border:1px solid rgba(23,56,62,.10)!important;
  border-radius:16px!important;
  padding:28px 18px 24px!important;
  box-shadow:0 10px 28px rgba(23,56,62,.07)!important;
  text-align:center!important;
  min-height:190px;
  height:100%;
  display:flex!important;
  flex-direction:column!important;
  align-items:center!important;
  justify-content:flex-start!important;
}
body.page-id-1361 .elementor-element-rskontact .elementor-heading-title{
  color:var(--rs-ink)!important;
  font-family:Poppins,sans-serif!important;
  font-weight:600!important;
  font-size:1.05rem!important;
}
body.page-id-1361 .elementor-element-rskontact .elementor-widget-text-editor,
body.page-id-1361 .elementor-element-rskontact .elementor-widget-text-editor p,
body.page-id-1361 .elementor-element-rskontact .elementor-widget-text-editor span{
  color:var(--rs-muted)!important;
  background:transparent!important;
  font-size:15px!important;
  line-height:1.45!important;
}
body.page-id-1361 .elementor-element-rskontact .elementor-widget-text-editor a{
  color:var(--rs-accent)!important;
  text-decoration:none!important;
  font-weight:600!important;
  background:transparent!important;
}
body.page-id-1361 .elementor-element-rskontact .elementor-widget-text-editor a:hover{
  color:var(--rs-accent-deep)!important;
}
body.page-id-1361 .elementor-element-rskontact .elementor-icon{
  color:var(--rs-accent)!important;
  margin-bottom:4px;
}
body.page-id-1361 .elementor-element-rskontact .elementor-icon svg{
  width:28px!important;
  height:28px!important;
  fill:var(--rs-accent)!important;
}
@media (max-width:1024px){
  body.page-id-1361 .elementor-element-e550d95 > .elementor-container{
    flex-wrap:wrap;
  }
  body.page-id-1361 .elementor-element-e550d95 > .elementor-container > .elementor-column{
    width:calc(50% - 9px)!important;
  }
}
@media (max-width:640px){
  body.page-id-1361 .elementor-element-e550d95 > .elementor-container > .elementor-column{
    width:100%!important;
  }
}
body.page-id-1361 .elementor-element-fc42df6{
  background-color:var(--rs-surface)!important;
}
body.page-id-1361 .elementor-element-f2f8aef{
  background-color:var(--rs-forest)!important;
  color:var(--rs-on-dark);
}
body.page-id-1361 .elementor-element-f2f8aef .elementor-heading-title,
body.page-id-1361 .elementor-element-f2f8aef .elementor-widget-text-editor,
body.page-id-1361 .elementor-element-f2f8aef .elementor-icon{
  color:var(--rs-on-dark)!important;
}
body.page-id-1361 .elementor-element-f2f8aef .elementor-button,
body.page-id-1361 .elementor-element-f2f8aef .elementor-button-link{
  background-color:var(--rs-accent)!important;
  color:var(--rs-on-accent)!important;
  border-color:var(--rs-accent)!important;
}
body.page-id-1361 .elementor-element-f2f8aef .rs-nl__field,
body.page-id-1361 .elementor-element-f2f8aef .rs-nl__field span{
  color:var(--rs-on-dark)!important;
}
body.page-id-1361 .elementor-element-f2f8aef .rs-nl__note{
  color:rgba(255,252,250,.82)!important;
}
body.page-id-1361 .elementor-element-f2f8aef .rs-nl__submit{
  background:var(--rs-accent)!important;
  color:var(--rs-on-accent)!important;
}

/* Homepage alternating section backgrounds (A/B rhythm) */
body.home .elementor-element-de4aaf6,
body.home .elementor-element-3a2c791,
body.home .elementor-element-8bbb2f0,
body.home .elementor-element-b0a9791,
body.home .elementor-element-rsfaqhd1,
body.home .elementor-element-rsfaq001,
body.home .elementor-element-rstrust1{
  background-color:var(--rs-surface-alt)!important;
}
body.home .elementor-element-7626a2c,
body.home .elementor-element-5bfced7,
body.home .elementor-element-d796670,
body.home .elementor-element-rsblog1{
  background-color:var(--rs-surface)!important;
}

/* Promo + newsletter: forest band (light text only) */
body.home .elementor-element-ae456a8,
body.home .elementor-element-f950bb0{
  background-color:var(--rs-forest)!important;
  color:var(--rs-on-dark);
}
body.home .elementor-element-ae456a8 .elementor-heading-title,
body.home .elementor-element-ae456a8 .elementor-widget-text-editor,
body.home .elementor-element-ae456a8 .elementor-icon,
body.home .elementor-element-f950bb0 .elementor-heading-title,
body.home .elementor-element-f950bb0 .elementor-widget-text-editor{
  color:var(--rs-on-dark)!important;
}
body.home .elementor-element-ae456a8 .elementor-button,
body.home .elementor-element-ae456a8 .elementor-button-link{
  background-color:var(--rs-accent)!important;
  color:var(--rs-on-accent)!important;
  border-color:var(--rs-accent)!important;
}
body.home .elementor-element-ae456a8 .elementor-button:hover,
body.home .elementor-element-ae456a8 .elementor-button-link:hover{
  background-color:var(--rs-accent-deep)!important;
  border-color:var(--rs-accent-deep)!important;
  color:var(--rs-on-accent)!important;
}
body.home .elementor-element-f950bb0 .rs-nl__field,
body.home .elementor-element-f950bb0 .rs-nl__field span{
  color:var(--rs-on-dark)!important;
}
body.home .elementor-element-f950bb0 .rs-nl__note{
  color:rgba(255,252,250,.82)!important;
}
body.home .elementor-element-f950bb0 .rs-nl__submit{
  background:var(--rs-accent)!important;
  color:var(--rs-on-accent)!important;
}
body.home .elementor-element-f950bb0 .rs-nl__submit:hover{
  background:var(--rs-accent-deep)!important;
}
body.home .elementor-element-f950bb0 .rs-nl__msg{
  background:rgba(255,252,250,.12);
  color:var(--rs-on-dark);
}

/* Newsletter: keep form | dog side-by-side on desktop */
body.home .elementor-element-f950bb0.e-con,
body.home .elementor-element-f950bb0{
  --flex-direction:row!important;
  --flex-wrap:nowrap!important;
  flex-direction:row!important;
  flex-wrap:nowrap!important;
  align-items:center!important;
}
body.home .elementor-element-ccde1c4{
  --width:min(560px, 52%)!important;
  width:52%!important;
  max-width:560px;
  flex:1 1 0!important;
  min-width:0!important;
}
body.home .elementor-element-66a7b2b{
  --width:42%!important;
  width:42%!important;
  flex:0 1 42%!important;
  min-width:0!important;
}
body.home .elementor-element-66a7b2b img{
  width:100%!important;
  height:auto!important;
  max-width:420px;
  object-fit:contain;
}
body.home .elementor-element-f950bb0 .rs-nl{
  max-width:100%;
  margin:0;
}
/* Left column: center Newsletter title + promo copy */
body.home .elementor-element-ccde1c4 .elementor-heading-title,
body.home .elementor-element-ccde1c4 .elementor-widget-heading,
body.home .elementor-element-ccde1c4 .elementor-widget-text-editor,
body.home .elementor-element-rsnlhd2,
body.home .elementor-element-nsdb9184d{
  text-align:center!important;
}
body.home .elementor-element-ccde1c4 .elementor-widget-heading .elementor-widget-container,
body.home .elementor-element-ccde1c4 .elementor-widget-text-editor .elementor-widget-container{
  text-align:center!important;
}
@media (max-width:900px){
  body.home .elementor-element-f950bb0.e-con,
  body.home .elementor-element-f950bb0{
    --flex-direction:column!important;
    --flex-wrap:wrap!important;
    flex-direction:column!important;
  }
  body.home .elementor-element-ccde1c4,
  body.home .elementor-element-66a7b2b{
    --width:100%!important;
    width:100%!important;
    flex:1 1 100%!important;
    max-width:100%;
  }
  body.home .elementor-element-f950bb0 .rs-nl{
    max-width:480px;
    margin:0 auto;
  }
}

/* Woo / shop contrast: cart, checkout, filters, PDP */
.woocommerce-cart .cart_totals .checkout-button,
.woocommerce-checkout #place_order,
.woocommerce div.product form.cart .single_add_to_cart_button{
  background-color:var(--rs-accent)!important;
  color:var(--rs-on-accent)!important;
  border-color:var(--rs-accent)!important;
}
.woocommerce-cart .cart_totals .checkout-button:hover,
.woocommerce-checkout #place_order:hover,
.woocommerce div.product form.cart .single_add_to_cart_button:hover{
  background-color:var(--rs-accent-deep)!important;
  border-color:var(--rs-accent-deep)!important;
  color:var(--rs-on-accent)!important;
}
.woocommerce div.product p.price,
.woocommerce ul.products li.product .price,
.woocommerce-cart .cart-subtotal .amount,
.woocommerce-cart .order-total .amount{
  color:var(--rs-accent)!important;
}
.woocommerce-info,
.woocommerce-message{
  border-top-color:var(--rs-accent)!important;
  color:var(--rs-ink)!important;
  background:var(--rs-surface-alt)!important;
}
.woocommerce-error{
  color:var(--rs-ink)!important;
}
body.woocommerce-shop .ct-sidebar,
body.post-type-archive-product .ct-sidebar,
.wpc-filters-widget-wrapper,
.wpc-filters-section{
  color:var(--rs-ink);
}
.wpc-filters-widget-wrapper .wpc-filter-title,
.wpc-filters-section .wpc-filter-title,
.ct-sidebar .widget-title{
  color:var(--rs-ink)!important;
}
.wpc-filters-widget-wrapper a,
.wpc-filters-section a,
.ct-sidebar a{
  color:var(--rs-ink);
}
.wpc-filters-widget-wrapper .wpc-checkbox-item input:checked + label,
.wpc-filters-widget-wrapper .wpc-filter-chip{
  color:var(--rs-ink);
}
.woocommerce-breadcrumb,
.woocommerce-breadcrumb a{
  color:var(--rs-muted)!important;
}
body.single-product .product_title,
body.single-product .summary .price{
  color:var(--rs-ink);
}
body.single-product .summary .price .amount{
  color:var(--rs-accent)!important;
}
.woocommerce table.shop_table th,
.woocommerce table.shop_table td,
.woocommerce-checkout .woocommerce-billing-fields label,
.woocommerce-checkout .woocommerce-additional-fields label{
  color:var(--rs-ink);
}
</style>';
}, 40);

// Trust injection: match new reviews block too
add_action('template_redirect', static function () {
    if (!is_front_page() || is_admin()) {
        return;
    }
    ob_start(static function ($html) {
        if (!is_string($html) || $html === '' || str_contains($html, 'rs-trust-stats')) {
            return $html;
        }
        if (!function_exists('rs_trust_stats_html')) {
            return $html;
        }
        $block = rs_trust_stats_html();
        if ($block === '') {
            return $html;
        }
        if (str_contains($html, 'class="rs-rev"')) {
            $out = preg_replace('/(<section[^>]*class="[^"]*rs-rev[^"]*"[^>]*>)/i', $block . '$1', $html, 1, $c);
            if ($c > 0 && is_string($out)) {
                return $out;
            }
        }
        return $html;
    });
}, 2);
