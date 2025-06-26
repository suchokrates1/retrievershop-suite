from pathlib import Path


def test_table_style_has_no_max_width():
    css_path = Path(__file__).resolve().parent.parent / "static" / "styles.css"
    css = css_path.read_text()
    assert "max-width: 1200px" not in css
    assert "width: 80px" in css
    assert "overflow-x: auto" in css
