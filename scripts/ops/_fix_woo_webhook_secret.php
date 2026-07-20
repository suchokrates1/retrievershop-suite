<?php
/** Set secret on webhooks 1 and 2 from WOO_WEBHOOK_SECRET env. */
$secret = getenv('WOO_WEBHOOK_SECRET') ?: '';
if (!$secret) {
    fwrite(STDERR, "missing secret\n");
    exit(1);
}
foreach (array(1, 2) as $id) {
    $w = new WC_Webhook($id);
    if (!$w->get_id()) {
        echo "missing webhook {$id}\n";
        continue;
    }
    $w->set_secret($secret);
    $w->set_status('active');
    $w->save();
    echo "updated id={$id} secret_len=" . strlen($secret) . " url=" . $w->get_delivery_url() . "\n";
}
