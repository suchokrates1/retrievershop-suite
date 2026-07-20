<?php
$ids = array(3422, 3496, 3511);
foreach ($ids as $id) {
    $p = wc_get_product($id);
    if (!$p) {
        echo "missing {$id}\n";
        continue;
    }
    $feat = $p->get_image_id();
    $gal = $p->get_gallery_image_ids();
    $url = $feat ? wp_get_attachment_url($feat) : '';
    echo "product={$id} featured={$feat} gallery_count=" . count($gal) . " url={$url}\n";
}
