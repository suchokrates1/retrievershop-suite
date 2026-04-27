"""Diagnostyka Alpine w Playwright - uruchamiac jako pytest."""
from playwright.sync_api import Page


def test_alpine_diag(logged_in_page: Page, live_url: str):
    """Diagnostyka stanu Alpine po zaladowaniu strony."""
    page = logged_in_page
    page.set_viewport_size({"width": 360, "height": 800})
    page.goto(f"{live_url}/")
    page.wait_for_load_state("networkidle")

    # 1. typeof Alpine
    alpine_type = page.evaluate("() => typeof Alpine")
    print(f"\n1. typeof Alpine = {alpine_type}")

    # 2. Alpine.version
    if alpine_type != "undefined":
        ver = page.evaluate("() => Alpine.version")
        print(f"2. Alpine.version = {ver}")
    else:
        print("2. Alpine NOT loaded from CDN!")

    # 3. x-data
    xdata = page.evaluate("""() => {
        const el = document.querySelector('[x-data]');
        return el ? el.getAttribute('x-data') : null;
    }""")
    print(f"3. x-data attr = {xdata}")

    # 4. _x_dataStack
    has_stack = page.evaluate("""() => {
        const el = document.querySelector('[x-data]');
        return el && el._x_dataStack ? true : false;
    }""")
    print(f"4. _x_dataStack present = {has_stack}")

    # 5. menu exists
    menu_exists = page.evaluate("() => !!document.querySelector('.mobile-menu')")
    print(f"5. .mobile-menu exists = {menu_exists}")

    # 6. all btn-ghost
    all_btns = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('button.btn-ghost')).map(b => ({
            classes: b.className,
            text: b.textContent.trim().substring(0, 50),
            visible: b.offsetParent !== null,
            w: b.getBoundingClientRect().width,
            h: b.getBoundingClientRect().height
        }));
    }""")
    for i, b in enumerate(all_btns):
        print(f"   btn[{i}]: classes={b['classes']}, visible={b['visible']}, {b['w']}x{b['h']}")

    # 7. JS click
    print("\n--- JS .click() ---")
    page.evaluate("() => document.querySelector('button.btn-ghost').click()")
    page.wait_for_timeout(1000)
    menu_cls = page.evaluate("() => document.querySelector('.mobile-menu').className")
    body_cls = page.evaluate("() => document.body.className")
    print(f"7. menu classes = {menu_cls}")
    print(f"8. body classes = {body_cls}")

    # 9. Alpine.$data
    try:
        data = page.evaluate("""() => {
            const el = document.querySelector('[x-data]');
            return Alpine.$data ? Alpine.$data(el) : 'no $data';
        }""")
        print(f"9. Alpine.$data = {data}")
    except Exception as e:
        print(f"9. err: {e}")

    assert False, "Diagnostic test - check output above"
