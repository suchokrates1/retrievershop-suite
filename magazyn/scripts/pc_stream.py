import re
import time
import requests


def main():
    s = requests.Session()
    login = s.get("http://localhost:8000/login", timeout=8)
    m = re.search(r'name="csrf_token" type="hidden" value="([^"]+)"', login.text)
    if not m:
        print("csrf token not found")
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
        timeout=(5, 20),
    )
    count = 0
    for line in r.iter_lines(decode_unicode=True):
        if not line:
            continue
        elapsed = time.time() - start
        print(f"{elapsed:6.1f}s | {line}")
        count += 1
        if count >= 30:
            break


if __name__ == "__main__":
    main()
