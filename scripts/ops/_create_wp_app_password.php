<?php
/**
 * Create Application Password for media uploads.
 * Usage: wp eval-file _create_wp_app_password.php --allow-root
 * Env: WP_APP_USER=retrievershop  WP_APP_PASS_NAME=magazyn-media
 */
$user_login = getenv('WP_APP_USER') ?: 'retrievershop';
$name = getenv('WP_APP_PASS_NAME') ?: 'magazyn-media';
$user = get_user_by('login', $user_login);
if (!$user) {
    fwrite(STDERR, "user not found: {$user_login}\n");
    exit(1);
}

// Revoke previous passwords with same name
if (class_exists('WP_Application_Passwords')) {
    $existing = WP_Application_Passwords::get_user_application_passwords($user->ID);
    foreach ($existing as $item) {
        if (($item['name'] ?? '') === $name) {
            WP_Application_Passwords::delete_application_password($user->ID, $item['uuid']);
        }
    }
    $created = WP_Application_Passwords::create_new_application_password(
        $user->ID,
        array('name' => $name)
    );
    if (is_wp_error($created)) {
        fwrite(STDERR, $created->get_error_message() . "\n");
        exit(1);
    }
    // $created = [password, item]
    echo $user_login . "\n" . $created[0] . "\n";
    exit(0);
}

fwrite(STDERR, "WP_Application_Passwords unavailable\n");
exit(1);
