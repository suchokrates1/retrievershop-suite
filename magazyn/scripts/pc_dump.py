import re
import json
import base64
import requests
import time


def main():
    s = requests.Session()
    login = s.get("http://localhost:8000/login", timeout=8)
    m = re.search(r"name=\"csrf_token\" type=\"hidden\" value=\"([^\"]+)\"", login.text)
    if not m:
        print("missing csrf")
        return
    csrf = m.group(1)
    s.post(
        "http://localhost:8000/login",
        data={"username": "admin", "password": "admin123", "csrf_token": csrf},
        timeout=8,
        allow_redirects=True,
    )

    start = time.time()
    r = s.get(
        "http://localhost:8000/allegro/price-check/stream",
        stream=True,
        timeout=(5, 60),
    )

    screenshot_saved = False
    offer_url = None
    count = 0
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        count += 1
        if time.time() - start > 45 or count > 200:
            break
        if not line.startswith("data: "):
            continue
        try:
            payload = json.loads(line[len("data: "):])
        except Exception:
            continue
        if isinstance(payload, dict):
            if (
                not offer_url
                and isinstance(payload.get("value"), str)
                and "https://allegro.pl/oferta/" in payload.get("value", "")
            ):
                try:
                    offer_url = json.loads(payload["value"]).get("url")
                except Exception:
                    pass
            if "image" in payload and not screenshot_saved:
                with open("/tmp/price_check_shot.png", "wb") as f:
                    f.write(base64.b64decode(payload["image"]))
                screenshot_saved = True
                print(f"saved_screenshot /tmp/price_check_shot.png t={time.time()-start:.1f}s")
                break

    if not offer_url:
        offer_url = "https://allegro.pl/oferta/17892897249"
    try:
        html = s.get(offer_url, timeout=20).text
        with open("/tmp/price_check_offer.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("saved_html /tmp/price_check_offer.html")
    except Exception as exc:
        print("html_error", exc)


if __name__ == "__main__":
    main()
