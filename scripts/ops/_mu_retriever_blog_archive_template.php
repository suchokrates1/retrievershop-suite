<?php
/**
 * Posts archive template for page_for_posts (/blog/).
 * Keeps metro mosaic look; WordPress treats this as the real blog index.
 */
if (!defined('ABSPATH')) {
    exit;
}

get_header();
?>
<div class="ct-container rs-blog-archive" data-rs-blog-archive="1">
	<?php
	// Prefer main query (archive), fall back to dedicated query inside helper.
	if (have_posts()) {
		$tiles_query = $GLOBALS['wp_query'];
		echo rs_blog_metro_from_query($tiles_query);
	} else {
		echo rs_blog_metro_html(40);
	}
	?>
</div>
<?php
get_footer();
