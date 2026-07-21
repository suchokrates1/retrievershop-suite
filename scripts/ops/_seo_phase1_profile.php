<?php
/**
 * Faza 1 SEO: tagline, telefon AIOSEO, homepage/kontakt meta, Local phone.
 * Run: docker exec retrievershop-wp php /tmp/_seo_phase1_profile.php
 */
require '/var/www/html/wp-load.php';

header('Content-Type: text/plain; charset=utf-8');

// Elementor kit hook wymaga zalogowanego admina przy update_option(blogdescription)
wp_set_current_user(1);
if (!current_user_can('manage_options')) {
    $admins = get_users(['role' => 'administrator', 'number' => 1, 'fields' => 'ID']);
    if ($admins) {
        wp_set_current_user((int) $admins[0]);
    }
}

$PHONE = '782 865 895';
$PHONE_E164 = '+48782865895';
$TAGLINE = 'Akcesoria spacerowe dla psów — szelki i smycze Truelove';
$HOME_TITLE = 'Retriever Shop — szelki i smycze dla psów | Truelove';
$HOME_DESC = 'Sklep Retriever Shop: szelki, smycze i akcesoria Truelove. Szybka wysyłka z Legnicy. Sprawdź rozmiary i kolory online.';
$KONTAKT_TITLE = 'Kontakt — Retriever Shop';
$KONTAKT_DESC = 'Skontaktuj się z Retriever Shop: tel. 782 865 895, e-mail kontakt@retrievershop.pl, Wrocławska 15/7, 59-220 Legnica.';

// Bezposredni UPDATE omija czesc hookow Elementor; fallback update_option
global $wpdb;
$wpdb->update($wpdb->options, ['option_value' => $TAGLINE], ['option_name' => 'blogdescription']);
wp_cache_delete('blogdescription', 'options');
wp_cache_delete('alloptions', 'options');
echo "tagline OK\n";

// AIOSEO options (JSON blob)
$raw = get_option('aioseo_options');
$opts = is_string($raw) ? json_decode($raw, true) : null;
if (!is_array($opts)) {
    echo "WARN: aioseo_options not array\n";
} else {
    if (!isset($opts['searchAppearance'])) {
        $opts['searchAppearance'] = [];
    }
    if (!isset($opts['searchAppearance']['global'])) {
        $opts['searchAppearance']['global'] = [];
    }
    $g =& $opts['searchAppearance']['global'];
    $g['metaDescription'] = $TAGLINE;
    if (!isset($g['schema']) || !is_array($g['schema'])) {
        $g['schema'] = [];
    }
    $g['schema']['phone'] = $PHONE_E164;
    $g['schema']['organizationDescription'] = $TAGLINE;

    if (!isset($opts['social'])) {
        $opts['social'] = [];
    }
    if (!isset($opts['social']['facebook'])) {
        $opts['social']['facebook'] = [];
    }
    $logo = 'https://retrievershop.pl/wp-content/uploads/2024/08/retriver-2.png';
    $opts['social']['facebook']['defaultImageSource'] = 'custom';
    $opts['social']['facebook']['defaultImageCustomFields'] = $logo;
    $opts['social']['facebook']['homePageImageSource'] = 'custom';
    $opts['social']['facebook']['homePageImageCustomFields'] = $logo;
    if (!isset($opts['social']['twitter'])) {
        $opts['social']['twitter'] = [];
    }
    $opts['social']['twitter']['defaultCardType'] = 'summary_large_image';
    $opts['social']['twitter']['defaultImageSource'] = 'custom';
    $opts['social']['twitter']['defaultImageCustomFields'] = $logo;

    update_option('aioseo_options', wp_json_encode($opts));
    echo "aioseo phone+tagline OK\n";
}

function rs_set_aioseo_post_meta($post_id, $title, $description) {
    if (!$post_id) {
        return;
    }
    update_post_meta($post_id, '_aioseo_title', $title);
    update_post_meta($post_id, '_aioseo_description', $description);
    // AIOSEO 4 stores JSON in aioseo_posts table when available — also set classic keys
    global $wpdb;
    $table = $wpdb->prefix . 'aioseo_posts';
    $exists = $wpdb->get_var($wpdb->prepare('SHOW TABLES LIKE %s', $table));
    if ($exists === $table) {
        $row = $wpdb->get_row($wpdb->prepare("SELECT id FROM {$table} WHERE post_id = %d", $post_id));
        $data = [
            'title' => $title,
            'description' => $description,
            'og_title' => $title,
            'og_description' => $description,
            'twitter_title' => $title,
            'twitter_description' => $description,
        ];
        if ($row) {
            $wpdb->update($table, $data, ['post_id' => $post_id]);
        } else {
            $data['post_id'] = $post_id;
            $wpdb->insert($table, $data);
        }
    }
}

$HOME_ID = (int) get_option('page_on_front');
if (!$HOME_ID) {
    $HOME_ID = 595; // known homepage from audit
}
rs_set_aioseo_post_meta($HOME_ID, $HOME_TITLE, $HOME_DESC);
echo "homepage meta post_id={$HOME_ID}\n";

$kontakt = get_page_by_path('kontakt');
if ($kontakt) {
    rs_set_aioseo_post_meta((int) $kontakt->ID, $KONTAKT_TITLE, $KONTAKT_DESC);
    echo "kontakt meta post_id={$kontakt->ID}\n";
}

// Replace old phone in Elementor/footer widgets if present in options
global $wpdb;
$old_phones = ['605864663', '605 864 663', '+48605864663', '48 605 864 663'];
foreach ($old_phones as $old) {
    $like = '%' . $wpdb->esc_like($old) . '%';
    $rows = $wpdb->get_results($wpdb->prepare(
        "SELECT meta_id, meta_value FROM {$wpdb->postmeta} WHERE meta_value LIKE %s LIMIT 50",
        $like
    ));
    foreach ($rows as $row) {
        $new = str_replace($old, $PHONE, $row->meta_value);
        if ($new !== $row->meta_value) {
            $wpdb->update($wpdb->postmeta, ['meta_value' => $new], ['meta_id' => $row->meta_id]);
            echo "replaced phone in meta_id={$row->meta_id}\n";
        }
    }
}

// Homepage Elementor copy fixes
$fixes = [
    'zapoznanania' => 'zapoznania',
    '10zł rabatu' => '10% rabatu',
    'Otrzymaj 10zł' => 'Otrzymaj 10%',
];
foreach ($fixes as $from => $to) {
    $like = '%' . $wpdb->esc_like($from) . '%';
    $rows = $wpdb->get_results($wpdb->prepare(
        "SELECT meta_id, meta_value FROM {$wpdb->postmeta} WHERE post_id = %d AND meta_value LIKE %s",
        $HOME_ID,
        $like
    ));
    foreach ($rows as $row) {
        $new = str_replace($from, $to, $row->meta_value);
        if ($new !== $row->meta_value) {
            $wpdb->update($wpdb->postmeta, ['meta_value' => $new], ['meta_id' => $row->meta_id]);
            echo "copy fix meta_id={$row->meta_id} {$from} -> {$to}\n";
        }
    }
}

echo "DONE phase1\n";
