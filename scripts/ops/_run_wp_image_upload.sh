#!/bin/bash
# Run on RPI. Pulls image URLs from minipc magazyn DB mapping and uploads to WP.
set -eu

docker cp /tmp/_wp_upload_allegro_images.php retrievershop-wp:/tmp/_wp_upload_allegro_images.php

# Product 3422 / 3496 with URLs passed as args:
#   bash _run_wp_image_upload.sh 3422 'url1|url2'
PRODUCT_ID="${1:?product id}"
URLS="${2:?urls pipe-separated}"

docker exec \
  -e WOO_PRODUCT_ID="$PRODUCT_ID" \
  -e IMAGE_URLS="$URLS" \
  retrievershop-wp \
  php /var/www/html/wp-cli.phar eval-file /tmp/_wp_upload_allegro_images.php --allow-root
