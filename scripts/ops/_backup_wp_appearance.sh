#!/bin/bash
# Backup wygladu retrievershop.pl (theme/Elementor/CSS/options) — NIE pelna baza.
set -euo pipefail
STAMP=$(date +%Y%m%d_%H%M%S)
HOST_DIR="$HOME/retrievershop-suite-ui-backups"
# Prefer existing shop backups dir if present
if [ -d "$HOME/retrievershop/backups" ]; then
  HOST_DIR="$HOME/retrievershop/backups/ui-appearance"
elif [ -d "$HOME/retrievershop-wp/backups" ]; then
  HOST_DIR="$HOME/retrievershop-wp/backups/ui-appearance"
fi
# Discover compose home
for d in "$HOME/retrievershop" "$HOME/retrievershop-wp" /home/suchokrates1/retrievershop; do
  if [ -f "$d/docker-compose.yml" ]; then
    COMPOSE_DIR="$d"
    break
  fi
done
COMPOSE_DIR="${COMPOSE_DIR:-$HOME/retrievershop}"
OUT="$HOST_DIR/$STAMP"
mkdir -p "$OUT"
echo "OUT=$OUT"
echo "COMPOSE_DIR=$COMPOSE_DIR"

# 1) Export options + Elementor pages via PHP inside WP container
docker exec retrievershop-wp php -r '
require "/var/www/html/wp-load.php";
$dir = "/tmp/ui-backup";
@mkdir($dir, 0755, true);
$dump = [];
$keys = [
  "blogname","blogdescription","template","stylesheet","current_theme",
  "theme_mods_blocksy","theme_mods_blocksy-child",
  "sidebars_widgets","widget_block","widget_text",
  "elementor_active_kit","elementor_scheme_color","elementor_scheme_typography",
  "elementor_container_width","elementor_cpt_support",
  "woocommerce_catalog_columns","woocommerce_catalog_rows",
  "woocommerce_shop_page_display","woocommerce_category_archive_display",
  "woocommerce_default_catalog_orderby","woocommerce_enable_ajax_add_to_cart",
  "wpc_filters","wpc_seo_rules","wpc_settings",
  "jet-woo-builder","jet-woo-builder-settings",
  "wp_dark_mode_settings","wp_dark_mode_switch",
  "active_plugins",
];
foreach ($keys as $k) {
  $dump[$k] = get_option($k);
}
// Also grab all options starting with blocksy / elementor / jet / wpc / ct_
global $wpdb;
$like_rows = $wpdb->get_results("SELECT option_name, option_value FROM {$wpdb->options}
  WHERE option_name LIKE \"blocksy%\"
     OR option_name LIKE \"%elementor%\"
     OR option_name LIKE \"jet%\"
     OR option_name LIKE \"wpc_%\"
     OR option_name LIKE \"wp_dark_mode%\"
     OR option_name LIKE \"theme_mods_%\"
     OR option_name LIKE \"woocommerce_%display%\"
     OR option_name LIKE \"woocommerce_catalog%\"");
foreach ($like_rows as $row) {
  $dump[$row->option_name] = maybe_unserialize($row->option_value);
}
file_put_contents("$dir/options.json", wp_json_encode($dump, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES));

// Key pages Elementor data
$page_ids = [595, 1037, 1361, 1976, 1977, 1978, 1979]; // home, o-nas, kontakt, shop, cart, checkout, account
$front = (int) get_option("page_on_front");
if ($front) $page_ids[] = $front;
$page_ids = array_unique($page_ids);
$pages = [];
foreach ($page_ids as $pid) {
  $post = get_post($pid);
  if (!$post) continue;
  $pages[$pid] = [
    "post_title" => $post->post_title,
    "post_name" => $post->post_name,
    "post_content" => $post->post_content,
    "post_status" => $post->post_status,
    "_elementor_data" => get_post_meta($pid, "_elementor_data", true),
    "_elementor_page_settings" => get_post_meta($pid, "_elementor_page_settings", true),
    "_elementor_template_type" => get_post_meta($pid, "_elementor_template_type", true),
    "_wp_page_template" => get_post_meta($pid, "_wp_page_template", true),
  ];
}
file_put_contents("$dir/pages-elementor.json", wp_json_encode($pages, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES));

// Elementor templates / kits
$tpl = get_posts(["post_type"=>["elementor_library","jet-woo-builder"],"posts_per_page"=>-1,"post_status"=>"any"]);
$templates = [];
foreach ($tpl as $t) {
  $templates[$t->ID] = [
    "post_title"=>$t->post_title,
    "post_type"=>$t->post_type,
    "post_status"=>$t->post_status,
    "_elementor_data"=>get_post_meta($t->ID,"_elementor_data",true),
    "_elementor_template_type"=>get_post_meta($t->ID,"_elementor_template_type",true),
  ];
}
file_put_contents("$dir/elementor-templates.json", wp_json_encode($templates, JSON_PRETTY_PRINT|JSON_UNESCAPED_UNICODE|JSON_UNESCAPED_SLASHES));

echo "PHP_EXPORT_OK dir=$dir pages=".count($pages)." templates=".count($templates)." options=".count($dump)."\n";
'

docker cp retrievershop-wp:/tmp/ui-backup/. "$OUT/"

# 2) Child theme + Blocksy dynamic CSS
docker cp retrievershop-wp:/var/www/html/wp-content/themes/blocksy-child "$OUT/blocksy-child" 2>/dev/null || true
docker cp retrievershop-wp:/var/www/html/wp-content/uploads/blocksy "$OUT/uploads-blocksy" 2>/dev/null || true
docker cp retrievershop-wp:/var/www/html/wp-content/uploads/elementor "$OUT/uploads-elementor" 2>/dev/null || true
docker cp retrievershop-wp:/var/www/html/wp-content/mu-plugins "$OUT/mu-plugins" 2>/dev/null || true

# 3) DB dump of options + elementor postmeta (narrow)
docker exec retrievershop-db sh -c 'mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE" \
  wp_options --where="option_name LIKE \"%blocksy%\" OR option_name LIKE \"%elementor%\" OR option_name LIKE \"theme_mods_%\" OR option_name LIKE \"wpc_%\" OR option_name LIKE \"jet%\" OR option_name LIKE \"wp_dark_mode%\" OR option_name IN (\"active_plugins\",\"stylesheet\",\"template\",\"blogdescription\")" \
  > /tmp/ui_options.sql' 2>/dev/null \
  || docker exec retrievershop-db bash -c 'source /dev/null; mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" $(echo $MYSQL_DATABASE) wp_options --no-tablespaces 2>/dev/null | head -c 1 >/dev/null'
# Fallback simpler dump via WP DB creds from wp-config
docker exec retrievershop-wp bash -c '
  DB=$(php -r "require \"/var/www/html/wp-load.php\"; echo DB_NAME;")
  USER=$(php -r "require \"/var/www/html/wp-load.php\"; echo DB_USER;")
  PASS=$(php -r "require \"/var/www/html/wp-load.php\"; echo DB_PASSWORD;")
  HOST=$(php -r "require \"/var/www/html/wp-load.php\"; echo DB_HOST;")
  mysqldump -h"$HOST" -u"$USER" -p"$PASS" "$DB" wp_options \
    --where="option_name LIKE \"%blocksy%\" OR option_name LIKE \"%elementor%\" OR option_name LIKE \"theme_mods_%\" OR option_name LIKE \"wpc_%\" OR option_name LIKE \"jet%\" OR option_name LIKE \"wp_dark_mode%\"" \
    > /tmp/ui_options.sql 2>/dev/null || true
  mysqldump -h"$HOST" -u"$USER" -p"$PASS" "$DB" wp_posts wp_postmeta \
    --where="1" --no-data > /tmp/ui_schema_hint.sql 2>/dev/null || true
'
docker cp retrievershop-wp:/tmp/ui_options.sql "$OUT/ui_options.sql" 2>/dev/null || echo "sql dump skipped"

# Manifest
{
  echo "stamp=$STAMP"
  echo "host=$(hostname)"
  echo "created=$(date -Iseconds)"
  echo "purpose=appearance-ui-backup-before-blocksy-redesign"
  ls -la "$OUT"
} > "$OUT/MANIFEST.txt"

# Tarball
tar -C "$HOST_DIR" -czf "$HOST_DIR/ui-appearance-$STAMP.tar.gz" "$STAMP"
echo "BACKUP_OK $HOST_DIR/ui-appearance-$STAMP.tar.gz"
ls -lh "$HOST_DIR/ui-appearance-$STAMP.tar.gz"
