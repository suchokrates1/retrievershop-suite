from magazyn.services.allegro_offer_content import allegro_description_to_html, extract_image_urls


def test_allegro_description_to_html_sections():
    html = allegro_description_to_html(
        {
            "sections": [
                {"items": [{"type": "TEXT", "content": "<p>Hello</p>"}]},
                {"items": [{"type": "IMAGE", "url": "https://example.com/a.jpg"}]},
            ]
        }
    )
    assert "<p>Hello</p>" in html
    assert "https://example.com/a.jpg" in html


def test_extract_image_urls():
    urls = extract_image_urls(
        {
            "images": [{"url": "https://cdn/a.jpg"}, "https://cdn/b.jpg"],
            "description": {
                "sections": [{"items": [{"type": "IMAGE", "url": "https://cdn/c.jpg"}]}]
            },
        }
    )
    assert urls == ["https://cdn/a.jpg", "https://cdn/b.jpg", "https://cdn/c.jpg"]
