<?php
/**
 * Plugin Name: Retriever color photo swatches
 * Description: PDP/shop: larger image swatches for pa_kolor with color name caption.
 */
if (!defined('ABSPATH')) {
    exit;
}

add_action('wp_head', static function () {
    if (is_admin()) {
        return;
    }
    if (!function_exists('is_woocommerce') || (!is_woocommerce() && !is_product())) {
        // still allow shop/archive product pages
        if (!is_shop() && !is_product_taxonomy() && !is_product()) {
            return;
        }
    }
    echo '<style id="rs-color-swatches">
/* Photo swatches for Kolor — caption under image */
body.single-product .variations tr:has([swatches-attr="attribute_pa_kolor"]) .label,
body.single-product .variations tr:has(#pa_kolor) .label{
  vertical-align:top;
  padding-top:10px;
}
body.single-product .cfvsw-swatches-container[swatches-attr="attribute_pa_kolor"],
body.single-product .cfvsw-swatches-container:has(.cfvsw-image-option){
  display:flex;
  flex-wrap:wrap;
  gap:12px 14px;
  align-items:flex-start;
}
body.single-product .cfvsw-swatches-option.cfvsw-image-option{
  width:76px!important;
  min-width:76px!important;
  min-height:76px!important;
  height:auto!important;
  border-radius:8px!important;
  display:flex!important;
  flex-direction:column!important;
  align-items:center!important;
  gap:6px;
  padding:0!important;
  overflow:visible!important;
  background:transparent!important;
  border:0!important;
}
body.single-product .cfvsw-swatches-option.cfvsw-image-option .cfvsw-swatch-inner{
  width:76px!important;
  height:76px!important;
  min-width:76px!important;
  min-height:76px!important;
  border-radius:8px!important;
  border:1px solid rgba(23,56,62,.18);
  box-shadow:none;
  background-position:center!important;
  background-size:cover!important;
}
body.single-product .cfvsw-swatches-option.cfvsw-image-option.cfvsw-selected-swatch .cfvsw-swatch-inner,
body.single-product .cfvsw-swatches-option.cfvsw-image-option[selected] .cfvsw-swatch-inner{
  border-color:var(--rs-accent,#C45C3E);
  outline:2px solid var(--rs-accent,#C45C3E);
  outline-offset:1px;
}
/* Unavailable / out-of-stock options: gray + not clickable */
body.single-product .cfvsw-swatches-option.cfvsw-swatches-disabled,
body.single-product .cfvsw-swatches-option.cfvsw-swatches-blur,
body.single-product .cfvsw-swatches-option.cfvsw-swatches-blur-cross,
body.single-product .cfvsw-swatches-option.cfvsw-swatches-blur-disable,
body.single-product .cfvsw-swatches-option.cfvsw-swatches-out-of-stock,
body.single-product .cfvsw-swatches-option.disabled,
body.single-product .cfvsw-swatches-option[disabled],
body.single-product .cfvsw-swatches-option.cfvsw-swatches-hide{
  opacity:.38!important;
  filter:grayscale(.85)!important;
  cursor:not-allowed!important;
  pointer-events:none!important;
}
body.single-product .cfvsw-swatches-option.cfvsw-label-option.cfvsw-swatches-disabled,
body.single-product .cfvsw-swatches-option.cfvsw-label-option.cfvsw-swatches-blur,
body.single-product .cfvsw-swatches-option.cfvsw-label-option.cfvsw-swatches-blur-cross{
  text-decoration:line-through;
  opacity:.4!important;
}
body.single-product .cfvsw-swatches-option.cfvsw-image-option::after{
  content:attr(data-title);
  display:block;
  width:76px;
  text-align:center;
  font-size:12px;
  line-height:1.25;
  color:var(--rs-ink,#1A3333);
  white-space:normal;
}
/* Shop cards: slightly larger color photos, tooltip already shows name */
body:not(.single-product) .cfvsw-swatches-option.cfvsw-image-option{
  min-width:36px!important;
  min-height:36px!important;
  border-radius:6px!important;
}
body:not(.single-product) .cfvsw-swatches-option.cfvsw-image-option .cfvsw-swatch-inner{
  border-radius:6px!important;
  background-size:cover!important;
}
</style>';
}, 40);
