#!/bin/bash
# Run on RPI. Reads TSV: woo_id \t magazyn_id \t count \t url|url|...
set -eu
MAP="${1:-/tmp/woo_img_map.tsv}"
PHP=/tmp/_wp_upload_allegro_images.php

docker cp "$PHP" retrievershop-wp:"$PHP"

ok=0
fail=0
skip=0
while IFS=$'\t' read -r woo_id mag_id count urls; do
  # skip log noise lines
  case "$woo_id" in
    ''|*[!0-9]*) continue ;;
  esac
  if [ -z "$urls" ] || [ "$count" = "0" ]; then
    echo "skip woo=$woo_id no_urls"
    skip=$((skip + 1))
    continue
  fi
  echo "=== woo=$woo_id mag=$mag_id imgs=$count ==="
  if docker exec \
      -e WOO_PRODUCT_ID="$woo_id" \
      -e IMAGE_URLS="$urls" \
      retrievershop-wp \
      php /var/www/html/wp-cli.phar eval-file "$PHP" --allow-root; then
    ok=$((ok + 1))
  else
    echo "FAIL woo=$woo_id"
    fail=$((fail + 1))
  fi
done < "$MAP"

echo "DONE ok=$ok fail=$fail skip=$skip"
