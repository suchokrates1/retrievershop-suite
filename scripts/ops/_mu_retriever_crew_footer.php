<?php
/**
 * Plugin Name: Retriever Crew + Footer Contact
 * Description: [rs_crew] — Ola / Suzi / Ja w nowoczesnych kartach; stopka kontakt + NIP.
 */
if (!defined('ABSPATH')) {
    exit;
}

const RS_COMPANY_NIP = '6912540707';
const RS_COMPANY_NAME = 'Alexandra Kaługa';
const RS_COMPANY_ADDRESS = 'Wrocławska 15/7, 59-220 Legnica';
const RS_COMPANY_PHONE = '782 865 895';
const RS_COMPANY_PHONE_TEL = '+48782865895';
const RS_COMPANY_EMAIL = 'kontakt@retrievershop.pl';

const RS_SUZI_BIRTH_YEAR = 2021;
const RS_SUZI_INSTAGRAM = 'https://www.instagram.com/suzi_labrador_/';
/** Publiczny profil FB Suziego — jeśli pusty, ikona FB nie jest renderowana. */
const RS_SUZI_FACEBOOK = '';

function rs_suzi_age_years(?int $as_of_year = null): int {
    $year = $as_of_year ?? (int) gmdate('Y');
    return max(1, $year - RS_SUZI_BIRTH_YEAR);
}

function rs_suzi_bio_text(): string {
    $age = rs_suzi_age_years();
    return $age . '-letni Labrador Retriever — inspiracja do powstania całej naszej działalności. Główny model oraz tester wszystkich akcesoriów, które możecie tu znaleźć.';
}

/**
 * Order: Ola → Suzi → Ja (left to right).
 */
function rs_crew_members(): array {
    return [
        [
            'name' => 'Ola',
            'role' => 'Alexandra',
            'image_id' => 2976,
            'text' => 'Założycielka i pomysłodawczyni sklepu Retriever Shop. Pasjonatka zwierząt od wielu lat. Interesuje się psią behawiorystyką, wychowaniem i zdrowym żywieniem.',
            'social' => [],
        ],
        [
            'name' => 'Suzi',
            'role' => 'Labrador Retriever',
            'image_id' => 2978,
            'text' => rs_suzi_bio_text(),
            'social' => array_values(array_filter([
                RS_SUZI_FACEBOOK !== '' ? [
                    'label' => 'Facebook',
                    'url' => RS_SUZI_FACEBOOK,
                    'icon' => 'facebook',
                ] : null,
                [
                    'label' => 'Instagram',
                    'url' => RS_SUZI_INSTAGRAM,
                    'icon' => 'instagram',
                ],
            ])),
        ],
        [
            'name' => 'Ja',
            'role' => 'Dawid',
            'image_id' => 2279,
            'text' => 'Typowy facet od spraw technicznych. Zajmuje się obsługą strony, tworzeniem grafik i innymi sprawami, na które szefowa nie ma czasu. To ja piszę te wszystkie bzdury, które tu czytacie.',
            'social' => [],
        ],
    ];
}

function rs_icon_svg(string $type): string {
    $icons = [
        'phone' => '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1.1-.3 1.2.4 2.5.6 3.8.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1C10.6 21 3 13.4 3 4c0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.6.6 3.8.1.4 0 .8-.3 1.1L6.6 10.8z"/></svg>',
        'email' => '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M20 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4-8 5L4 8V6l8 5 8-5v2z"/></svg>',
        'pin' => '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M12 2C8.1 2 5 5.1 5 9c0 5.2 7 13 7 13s7-7.8 7-13c0-3.9-3.1-7-7-7zm0 9.5c-1.4 0-2.5-1.1-2.5-2.5S10.6 6.5 12 6.5s2.5 1.1 2.5 2.5S13.4 11.5 12 11.5z"/></svg>',
        'nip' => '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zm2 16H8v-2h8v2zm0-4H8v-2h8v2zm-3-5V3.5L18.5 9H13z"/></svg>',
        'facebook' => '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M22 12.07C22 6.48 17.52 2 11.93 2S1.86 6.48 1.86 12.07c0 5.02 3.66 9.18 8.44 9.93v-7.02H7.9v-2.91h2.4V9.84c0-2.37 1.41-3.68 3.57-3.68 1.03 0 2.12.19 2.12.19v2.33h-1.2c-1.18 0-1.55.73-1.55 1.48v1.78h2.64l-.42 2.91h-2.22V22c4.78-.75 8.44-4.91 8.44-9.93z"/></svg>',
        'instagram' => '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M7 2h10a5 5 0 0 1 5 5v10a5 5 0 0 1-5 5H7a5 5 0 0 1-5-5V7a5 5 0 0 1 5-5zm0 2a3 3 0 0 0-3 3v10a3 3 0 0 0 3 3h10a3 3 0 0 0 3-3V7a3 3 0 0 0-3-3H7zm11.5 1.5a1 1 0 1 1 0 2 1 1 0 0 1 0-2zM12 7a5 5 0 1 1 0 10 5 5 0 0 1 0-10zm0 2a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/></svg>',
    ];
    return $icons[$type] ?? '';
}

add_shortcode('rs_suzi_bio', static function () {
    return '<p class="rs-suzi-bio">' . esc_html(rs_suzi_bio_text()) . '</p>';
});

add_filter('elementor/widget/render_content', static function ($content, $widget) {
    if (!is_string($content) || $content === '') {
        return $content;
    }
    if (stripos($content, 'Labrador Retriever') === false || stripos($content, 'letni') === false) {
        return $content;
    }
    $age = rs_suzi_age_years();
    $content = preg_replace('/\d+\s*-?\s*letni(\s+Labrador Retriever)/iu', $age . '-letni$1', $content, 1);
    return $content;
}, 20, 2);

add_shortcode('rs_crew', static function ($atts = []) {
    $atts = shortcode_atts([
        'title' => '1',
    ], $atts, 'rs_crew');
    $show_title = $atts['title'] !== '0' && $atts['title'] !== 'false';

    $items = rs_crew_members();
    $cards = '';
    foreach ($items as $m) {
        $img = wp_get_attachment_image(
            (int) $m['image_id'],
            'medium_large',
            false,
            [
                'class' => 'rs-crew__img',
                'alt' => $m['name'] . ' — ' . $m['role'],
                'loading' => 'lazy',
            ]
        );
        if (!$img) {
            continue;
        }
        $social = '';
        if (!empty($m['social'])) {
            $social .= '<div class="rs-crew__social" aria-label="Media społecznościowe — ' . esc_attr($m['name']) . '">';
            foreach ($m['social'] as $s) {
                $social .= '<a class="rs-crew__social-link" href="' . esc_url($s['url']) . '" target="_blank" rel="noopener noreferrer" aria-label="' . esc_attr($s['label']) . '">'
                    . rs_icon_svg($s['icon'])
                    . '</a>';
            }
            $social .= '</div>';
        }
        $cards .= '<article class="rs-crew__card">'
            . '<div class="rs-crew__media">' . $img . '</div>'
            . '<div class="rs-crew__body">'
            . '<h3 class="rs-crew__name">' . esc_html($m['name']) . '</h3>'
            . '<p class="rs-crew__role">' . esc_html($m['role']) . '</p>'
            . '<p class="rs-crew__text">' . esc_html($m['text']) . '</p>'
            . $social
            . '</div>'
            . '</article>';
    }
    if ($cards === '') {
        return '';
    }
    $head = '';
    if ($show_title) {
        $head = '<p class="rs-crew__eyebrow">Poznaj naszą małą rodzinę</p>'
            . '<h2 class="rs-crew__title">Załoga</h2>';
    }
    return '<section class="rs-crew" aria-label="Załoga Retriever Shop">'
        . $head
        . '<div class="rs-crew__grid">' . $cards . '</div>'
        . '</section>';
});

add_action('wp_head', static function () {
    if (is_admin()) {
        return;
    }
    echo '<style id="rs-crew-footer">
.rs-crew{padding:8px 0 8px;text-align:center}
.rs-crew__eyebrow{margin:0 0 6px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--rs-muted,#5A6B6B);font-family:Poppins,sans-serif}
.rs-crew__title{margin:0 0 32px;font-size:clamp(1.75rem,2.6vw,2.25rem);color:var(--rs-ink,#1A3333);font-weight:700;font-family:Poppins,sans-serif}
.rs-crew__grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;text-align:left;max-width:1100px;margin:0 auto;padding:0 8px}
.rs-crew__card{
  margin:0;
  background:#fff;
  border:1px solid rgba(23,56,62,.10);
  border-radius:16px;
  box-shadow:0 10px 28px rgba(23,56,62,.07);
  overflow:hidden;
  display:flex;
  flex-direction:column;
  height:100%;
  transition:transform .2s ease, box-shadow .2s ease;
}
.rs-crew__card:hover{transform:translateY(-3px);box-shadow:0 14px 34px rgba(23,56,62,.11)}
.rs-crew__media{aspect-ratio:4/3;overflow:hidden;background:var(--rs-surface-alt,#EEF2F1)}
.rs-crew__img{width:100%;height:100%;object-fit:cover;display:block}
.rs-crew__body{padding:20px 18px 22px;display:flex;flex-direction:column;flex:1}
.rs-crew__name{margin:0 0 2px;font-size:1.35rem;color:var(--rs-forest,#17383E);font-family:Poppins,sans-serif;font-weight:700}
.rs-crew__role{margin:0 0 12px;font-size:13px;color:var(--rs-accent,#C45C3E);font-weight:600;letter-spacing:.02em}
.rs-crew__text{margin:0;font-size:15px;line-height:1.55;color:var(--rs-muted,#5A6B6B);flex:1}
.rs-crew__social{display:flex;gap:10px;margin-top:16px;justify-content:flex-start}
.rs-crew__social-link{
  width:40px;height:40px;border-radius:999px;
  display:inline-flex;align-items:center;justify-content:center;
  background:rgba(23,56,62,.06);color:var(--rs-forest,#17383E);
  transition:background .18s ease, color .18s ease, transform .18s ease;
}
.rs-crew__social-link:hover{background:var(--rs-accent,#C45C3E);color:#FFFCFA;transform:translateY(-1px)}
.rs-crew__social-link svg{width:18px;height:18px;display:block}
@media (max-width:900px){.rs-crew__grid{grid-template-columns:1fr;max-width:420px}}

/* Footer contact with icons */
.rs-footer-contact{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.rs-footer-contact li{display:flex;align-items:flex-start;gap:10px;margin:0;line-height:1.35;color:inherit}
.rs-footer-contact a{color:inherit;text-decoration:none}
.rs-footer-contact a:hover{color:var(--rs-accent,#C45C3E);text-decoration:underline}
.rs-footer-contact__icon{flex:0 0 22px;width:22px;height:22px;margin-top:1px;color:var(--theme-palette-color-1,#C45C3E);opacity:.95}
.rs-footer-contact__icon svg{width:22px;height:22px;display:block}
.rs-footer-contact__label{display:block;font-size:11px;letter-spacing:.04em;text-transform:uppercase;opacity:.7;margin-bottom:2px}
.rs-footer-contact__val{display:block;font-size:14px}
.ct-footer .rs-footer-contact{color:var(--theme-palette-color-8,#fff)}
.ct-footer .rs-footer-contact__icon{color:#F0C4B4}
</style>';
}, 42);

function rs_footer_contact_html(): string {
    $rows = [
        ['phone', 'Telefon', '<a href="tel:' . esc_attr(RS_COMPANY_PHONE_TEL) . '">' . esc_html(RS_COMPANY_PHONE) . '</a>'],
        ['email', 'E-mail', '<a href="mailto:' . esc_attr(RS_COMPANY_EMAIL) . '">' . esc_html(RS_COMPANY_EMAIL) . '</a>'],
        ['pin', 'Adres', esc_html(RS_COMPANY_ADDRESS)],
        ['nip', 'NIP', esc_html(RS_COMPANY_NIP)],
    ];
    $html = '<ul class="rs-footer-contact">';
    foreach ($rows as [$type, $label, $val]) {
        $html .= '<li>'
            . '<span class="rs-footer-contact__icon">' . rs_icon_svg($type) . '</span>'
            . '<span><span class="rs-footer-contact__label">' . esc_html($label) . '</span>'
            . '<span class="rs-footer-contact__val">' . $val . '</span></span>'
            . '</li>';
    }
    $html .= '</ul>';
    return $html;
}
