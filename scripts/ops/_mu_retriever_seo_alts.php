<?php
/**
 * MU: fill empty alt on known images (incl. Seraph Accel lzl placeholders).
 */
add_action('template_redirect', function () {
    ob_start(static function ($html) {
        if ($html === '' || stripos($html, '<img') === false) {
            return $html;
        }

        $map = [
            'user-avatar-1_optimized.webp' => 'Zdjęcie klienta — opinia o Retriever Shop',
            'user-avatar-2_optimized.webp' => 'Zdjęcie klienta — opinia o Retriever Shop',
            'user-avatar-3_optimized.webp' => 'Zdjęcie klienta — opinia o Retriever Shop',
            'payment-icons-footer.svg' => 'Metody płatności: karta, BLIK, przelew',
            'wp-image-230' => 'Metody płatności: karta, BLIK, przelew',
        ];

        foreach ($map as $needle => $alt) {
            $html = preg_replace_callback(
                '/<img\b[^>]*>/i',
                static function ($m) use ($needle, $alt) {
                    $tag = $m[0];
                    if (stripos($tag, $needle) === false) {
                        return $tag;
                    }
                    if (preg_match('/\balt=(["\'])(.*?)\1/is', $tag, $am)) {
                        if (trim($am[2]) !== '') {
                            return $tag;
                        }
                        return preg_replace(
                            '/\balt=(["\'])(.*?)\1/is',
                            'alt="' . esc_attr($alt) . '"',
                            $tag,
                            1
                        );
                    }
                    return preg_replace('/<img\b/i', '<img alt="' . esc_attr($alt) . '"', $tag, 1);
                },
                $html
            );
        }

        return $html;
    });
}, 0);

add_action('init', static function () {
    $cur = get_post_meta(230, '_wp_attachment_image_alt', true);
    if ($cur === '' || $cur === false) {
        update_post_meta(230, '_wp_attachment_image_alt', 'Metody płatności: karta, BLIK, przelew');
    }
}, 20);
