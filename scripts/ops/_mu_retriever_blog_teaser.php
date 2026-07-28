<?php
/**
 * Plugin Name: Retriever Blog
 * Description: WP posts archive (/blog/ as page_for_posts) + metro grid look + homepage teaser.
 */
if (!defined('ABSPATH')) {
    exit;
}

function rs_blog_url(): string {
    $pfp = (int) get_option('page_for_posts');
    if ($pfp > 0) {
        $link = get_permalink($pfp);
        if (is_string($link) && $link !== '') {
            return $link;
        }
    }
    $page = get_page_by_path('blog');
    if ($page) {
        return get_permalink($page);
    }
    return home_url('/blog/');
}

/**
 * True on the Posts page (/blog/), not the static front page.
 */
function rs_is_posts_archive(): bool {
    return is_home() && !is_front_page();
}

function rs_blog_thumb_url(int $post_id, string $size = 'large'): string {
    $url = get_the_post_thumbnail_url($post_id, $size);
    if ($url) {
        return $url;
    }
    return 'https://retrievershop.pl/wp-content/uploads/2024/08/paw-pattern-2.svg';
}

/**
 * Build metro mosaic from an existing WP_Query (e.g. main posts archive).
 */
function rs_blog_metro_from_query(WP_Query $q): string {
    if (!$q->have_posts()) {
        return '';
    }

    $tiles = [];
    while ($q->have_posts()) {
        $q->the_post();
        $id = (int) get_the_ID();
        $tiles[] = [
            'url' => get_permalink(),
            'img' => rs_blog_thumb_url($id, 'large'),
            'title' => get_the_title(),
            'date' => get_the_date('d/m/Y'),
            'date_c' => get_the_date('c'),
            'excerpt' => wp_trim_words(get_the_excerpt() ?: wp_strip_all_tags(get_the_content()), 22),
        ];
    }
    // Don't wp_reset_postdata() when using main query mid-template — reset after render.
    wp_reset_postdata();

    return rs_blog_metro_render_tiles($tiles);
}

/**
 * Metro mosaic inspired by Vestmedia The Plus "list-isotope-metro" style-1.
 */
function rs_blog_metro_html(int $limit = 24): string {
    $q = new WP_Query([
        'post_type' => 'post',
        'post_status' => 'publish',
        'posts_per_page' => max(1, min(40, $limit)),
        'ignore_sticky_posts' => true,
        'orderby' => 'date',
        'order' => 'DESC',
    ]);
    return rs_blog_metro_from_query($q);
}

/** @param list<array{url:string,img:string,title:string,date:string,date_c:string,excerpt:string}> $tiles */
function rs_blog_metro_render_tiles(array $tiles): string {
    if (!$tiles) {
        return '';
    }

    $tile_html = static function (array $t, string $mod): string {
        return '<a class="rs-metro__item rs-metro__item--' . esc_attr($mod) . '" href="' . esc_url($t['url']) . '">'
            . '<span class="rs-metro__bg" style="background-image:url(' . esc_url($t['img']) . ')"></span>'
            . '<span class="rs-metro__shade" aria-hidden="true"></span>'
            . '<span class="rs-metro__content">'
            . '<time class="rs-metro__date" datetime="' . esc_attr($t['date_c']) . '">' . esc_html($t['date']) . '</time>'
            . '<span class="rs-metro__title">' . esc_html($t['title']) . '</span>'
            . '<span class="rs-metro__excerpt">' . esc_html($t['excerpt']) . '</span>'
            . '</span></a>';
    };

    // A → B (mirror) → C (3 equal) → A…
    $blocks = '';
    $n = count($tiles);
    $i = 0;
    $phase = 0; // 0=A, 1=B, 2=C
    while ($i < $n) {
        $left = $n - $i;
        if ($phase === 0) {
            $blocks .= '<div class="rs-metro__block rs-metro__block--a">';
            if ($left >= 1) {
                $blocks .= $tile_html($tiles[$i++], 'large');
            }
            $blocks .= '<div class="rs-metro__stack">';
            if ($i < $n) {
                $blocks .= $tile_html($tiles[$i++], 'small');
            }
            if ($i < $n) {
                $blocks .= $tile_html($tiles[$i++], 'small');
            }
            $blocks .= '</div></div>';
        } elseif ($phase === 1) {
            $blocks .= '<div class="rs-metro__block rs-metro__block--b">';
            $blocks .= '<div class="rs-metro__stack">';
            if ($i < $n) {
                $blocks .= $tile_html($tiles[$i++], 'small');
            }
            if ($i < $n) {
                $blocks .= $tile_html($tiles[$i++], 'small');
            }
            $blocks .= '</div>';
            if ($i < $n) {
                $blocks .= $tile_html($tiles[$i++], 'large');
            }
            $blocks .= '</div>';
        } else {
            $blocks .= '<div class="rs-metro__block rs-metro__block--c">';
            for ($k = 0; $k < 3 && $i < $n; $k++) {
                $blocks .= $tile_html($tiles[$i++], 'third');
            }
            $blocks .= '</div>';
        }
        $phase = ($phase + 1) % 3;
    }

    return '<section class="rs-metro" aria-label="Wpisy na blogu">'
        . $blocks
        . '</section>';
}

add_shortcode('rs_blog_metro', static function ($atts = []) {
    $atts = shortcode_atts(['limit' => '24'], $atts, 'rs_blog_metro');
    return rs_blog_metro_html((int) $atts['limit']);
});

/**
 * /blog/ = real WP posts archive (Settings → Reading → Posts page).
 * Stay on Blocksy's archive canvas so type-2 hero renders; replace only the cards.
 */
add_filter('blocksy:posts-listing:canvas:custom-output', static function ($out) {
    if (!function_exists('rs_is_posts_archive') || !rs_is_posts_archive()) {
        return $out;
    }

    $html = '';
    if (function_exists('blocksy_output_hero_section')) {
        $html .= blocksy_output_hero_section(['type' => 'type-2']);
    }

    $attrs = '';
    if (function_exists('blocksy_sidebar_position_attr')) {
        $attrs .= ' ' . wp_kses_post(blocksy_sidebar_position_attr());
    }
    if (function_exists('blocksy_get_v_spacing')) {
        $attrs .= ' ' . blocksy_get_v_spacing();
    }

    $html .= '<div class="ct-container rs-blog-archive" data-rs-blog-archive="1"' . $attrs . '>';
    $html .= '<section>' . rs_blog_metro_html(40) . '</section>';
    ob_start();
    get_sidebar();
    $html .= ob_get_clean();
    $html .= '</div>';

    return $html;
}, 10);

/** Ensure archive query can feed enough posts for the mosaic. */
add_action('pre_get_posts', static function ($q) {
    if (is_admin() || !$q instanceof WP_Query || !$q->is_main_query()) {
        return;
    }
    if (!$q->is_home() || $q->is_front_page()) {
        return;
    }
    $q->set('posts_per_page', 40);
    $q->set('ignore_sticky_posts', true);
});

add_shortcode('rs_blog_teaser', static function ($atts = []) {
    $atts = shortcode_atts([
        'limit' => '3',
        'title' => 'Blog',
        'subtitle' => 'Porady, zdjęcia z terenu i historie z Retriever Shop.',
        'more' => 'Zobacz wszystkie wpisy',
    ], $atts, 'rs_blog_teaser');

    $q = new WP_Query([
        'post_type' => 'post',
        'post_status' => 'publish',
        'posts_per_page' => max(1, min(6, (int) $atts['limit'])),
        'ignore_sticky_posts' => true,
    ]);
    if (!$q->have_posts()) {
        return '';
    }

    $blog_url = rs_blog_url();
    $cards = '';
    while ($q->have_posts()) {
        $q->the_post();
        $img = esc_url(rs_blog_thumb_url(get_the_ID(), 'medium_large'));
        $cards .= '<a class="rs-blog-card" href="' . esc_url(get_permalink()) . '">'
            . '<span class="rs-blog-card__media"><img class="rs-blog-card__img" src="' . $img . '" alt="' . esc_attr(get_the_title()) . '" loading="lazy" /></span>'
            . '<span class="rs-blog-card__body">'
            . '<time class="rs-blog-card__date" datetime="' . esc_attr(get_the_date('c')) . '">' . esc_html(get_the_date()) . '</time>'
            . '<span class="rs-blog-card__title">' . esc_html(get_the_title()) . '</span>'
            . '<span class="rs-blog-card__excerpt">' . esc_html(wp_trim_words(get_the_excerpt() ?: wp_strip_all_tags(get_the_content()), 18)) . '</span>'
            . '</span></a>';
    }
    wp_reset_postdata();

    return '<section class="rs-blog-teaser" aria-label="Blog">'
        . '<header class="rs-blog-teaser__head">'
        . '<h2 class="rs-blog-teaser__title">' . esc_html($atts['title']) . '</h2>'
        . '<p class="rs-blog-teaser__sub">' . esc_html($atts['subtitle']) . '</p>'
        . '</header>'
        . '<div class="rs-blog-teaser__grid">' . $cards . '</div>'
        . '<p class="rs-blog-teaser__more"><a href="' . esc_url($blog_url) . '">' . esc_html($atts['more']) . ' →</a></p>'
        . '</section>';
});

add_action('wp_head', static function () {
    if (is_admin()) {
        return;
    }
    echo '<style id="rs-blog-css">
/* Homepage teaser */
.rs-blog-teaser{max-width:100%;margin:0 auto;padding:8px 0 12px;color:var(--rs-ink,#1A3333)}
.rs-blog-teaser__head{text-align:center;margin:0 0 28px}
.rs-blog-teaser__title{margin:0 0 8px;font-family:Poppins,sans-serif;font-size:clamp(28px,3.5vw,40px);font-weight:600;line-height:1.15}
.rs-blog-teaser__sub{margin:0 auto;max-width:520px;font-size:15px;line-height:1.45;color:var(--rs-muted,#5A6B6B)}
.rs-blog-teaser__grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}
.rs-blog-card{display:flex;flex-direction:column;text-decoration:none;color:inherit;background:#fff;border:1px solid rgba(26,51,51,.08);border-radius:14px;overflow:hidden;box-shadow:0 8px 24px rgba(26,51,51,.06);transition:transform .35s ease,box-shadow .35s ease}
.rs-blog-card:hover{transform:translateY(-3px);box-shadow:0 12px 28px rgba(26,51,51,.12)}
.rs-blog-card__media{display:block;aspect-ratio:16/10;background:var(--rs-surface-alt,#EEF2F1);overflow:hidden}
.rs-blog-card__img{width:100%!important;height:100%!important;object-fit:cover!important;display:block;margin:0!important}
.rs-blog-card__body{display:flex;flex-direction:column;gap:8px;padding:14px 16px 18px}
.rs-blog-card__date{font-size:12px;color:var(--rs-muted,#5A6B6B)}
.rs-blog-card__title{font-size:17px;font-weight:700;line-height:1.3;color:var(--rs-ink,#1A3333)}
.rs-blog-card__excerpt{font-size:14px;line-height:1.45;color:var(--rs-muted,#5A6B6B)}
.rs-blog-teaser__more{margin:22px 0 0;text-align:center}
.rs-blog-teaser__more a{color:var(--rs-accent,#C45C3E);font-weight:600;text-decoration:none}
@media (max-width:900px){.rs-blog-teaser__grid{grid-template-columns:1fr 1fr}}
@media (max-width:560px){.rs-blog-teaser__grid{grid-template-columns:1fr}}

/* Metro blocks: A large+stack | B mirror | C three squares */
.rs-metro{max-width:1200px;margin:0 auto 48px;padding:8px 20px 24px;display:flex;flex-direction:column;gap:12px}
.rs-metro__block--a,.rs-metro__block--b{
  display:grid;
  grid-template-columns:2fr 1fr;
  gap:12px;
  /* wysokość = szerokość dużej (2/3 kontenera) → kwadrat */
  --rs-metro-h:calc((min(1200px, 100vw) - 40px - 12px) * 2 / 3);
  height:var(--rs-metro-h);
  max-height:560px;
}
.rs-metro__block--b{grid-template-columns:1fr 2fr}
.rs-metro__stack{display:grid;grid-template-rows:1fr 1fr;gap:12px;min-height:0}
.rs-metro__block--c{
  display:grid;
  grid-template-columns:repeat(3,minmax(0,1fr));
  gap:12px;
}
.rs-metro__block--c .rs-metro__item{aspect-ratio:1}
.rs-metro__item{
  position:relative;display:block;overflow:hidden;border-radius:14px;
  text-decoration:none;color:var(--rs-on-dark,#FFFCFA);min-height:0;height:100%;
  box-shadow:0 10px 28px rgba(26,51,51,.12);
}
.rs-metro__bg{
  position:absolute;inset:0;
  background-size:cover;background-position:center;
  transform:scale(1.02);transition:transform .55s cubic-bezier(.22,1,.36,1);
}
.rs-metro__item:hover .rs-metro__bg{transform:scale(1.08)}
.rs-metro__shade{
  position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(23,56,62,.15) 10%,rgba(23,56,62,.72) 100%);
}
.rs-metro__item:hover .rs-metro__shade{
  background:linear-gradient(180deg,rgba(23,56,62,.25) 0%,rgba(23,56,62,.82) 100%);
}
.rs-metro__content{
  position:absolute;left:0;right:0;bottom:0;z-index:2;
  display:flex;flex-direction:column;gap:6px;padding:16px;
}
.rs-metro__date{font-size:12px;opacity:.85}
.rs-metro__title{
  font-family:Poppins,sans-serif;font-weight:700;line-height:1.25;
  font-size:clamp(14px,1.4vw,22px);
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;
}
.rs-metro__excerpt{
  font-size:13px;line-height:1.4;opacity:0;max-height:0;overflow:hidden;
  transition:opacity .3s ease,max-height .3s ease;
}
.rs-metro__item:hover .rs-metro__excerpt{opacity:.92;max-height:4.5em}
@media (max-width:900px){
  .rs-metro__block--a,.rs-metro__block--b{
    --rs-metro-h:calc((100vw - 40px - 12px) * 2 / 3);
    max-height:420px;
  }
  .rs-metro__block--c{grid-template-columns:1fr; }
  .rs-metro__block--c .rs-metro__item{aspect-ratio:16/10}
  .rs-metro__excerpt{opacity:.9;max-height:3.2em}
}
@media (max-width:640px){
  .rs-metro__block--a,.rs-metro__block--b{
    grid-template-columns:1fr;
    height:auto;
    max-height:none;
  }
  .rs-metro__block--a .rs-metro__item--large,
  .rs-metro__block--b .rs-metro__item--large{aspect-ratio:1}
  .rs-metro__stack{grid-template-rows:none;grid-template-columns:1fr 1fr}
  .rs-metro__stack .rs-metro__item{aspect-ratio:1}
}
body.blog #main-container,
body.home.blog #main-container,
body.page-id-5913 #main-container,
body.page-slug-blog #main-container{background:var(--rs-surface-alt,#EEF2F1)}
body.blog .rs-blog-archive{width:100%}

/* Blog image standard: 1:1 / 1200px derivatives */
.rs-metro__bg{background-size:cover;background-position:center}
.single-post .rs-blog-img,
.single-post figure.rs-blog-img,
.single-post .wp-block-image.rs-blog-img{
  margin:1.25rem auto;max-width:min(100%,720px);
}
.single-post .rs-blog-img img,
.single-post figure.rs-blog-img img{
  width:100%;height:auto;aspect-ratio:1/1;object-fit:cover;
  border-radius:12px;display:block;
}
.single-post .rs-blog-img figcaption{
  margin-top:.5rem;font-size:13px;line-height:1.4;color:var(--rs-muted,#5A6B6B);text-align:center;
}
</style>';
}, 40);
