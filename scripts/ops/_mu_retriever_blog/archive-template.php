<?php
/**
 * Fallback posts archive template (kept for safety).
 * Primary path: blocksy:posts-listing:canvas:custom-output in retriever-blog-teaser.php
 * so Blocksy type-2 hero stays intact.
 */
if (!defined('ABSPATH')) {
    exit;
}

get_header();

if (function_exists('blocksy_output_hero_section')) {
    echo blocksy_output_hero_section(['type' => 'type-2']);
}
?>
<div class="ct-container rs-blog-archive" data-rs-blog-archive="1">
	<?php echo function_exists('rs_blog_metro_html') ? rs_blog_metro_html(40) : ''; ?>
</div>
<?php
get_footer();
