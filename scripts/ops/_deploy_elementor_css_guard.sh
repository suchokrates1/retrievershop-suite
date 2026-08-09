#!/bin/bash
set -eu
BASE="$HOME/retrievershop"
docker cp "$BASE/_mu_retriever_elementor_css_guard.php" retrievershop-wp:/var/www/html/wp-content/mu-plugins/retriever-elementor-css-guard.php
if [ -d "$BASE/wp-app/wp-content/mu-plugins" ]; then
  sudo cp "$BASE/_mu_retriever_elementor_css_guard.php" "$BASE/wp-app/wp-content/mu-plugins/retriever-elementor-css-guard.php" || true
fi
docker exec retrievershop-wp chown www-data:www-data /var/www/html/wp-content/mu-plugins/retriever-elementor-css-guard.php
docker exec retrievershop-wp ls -la /var/www/html/wp-content/mu-plugins/retriever-elementor-css-guard.php
docker cp "$BASE/_check_elementor_css_guard.php" retrievershop-wp:/tmp/_check_elementor_css_guard.php
docker exec retrievershop-wp php /tmp/_check_elementor_css_guard.php
