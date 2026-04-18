"""Szybka diagnostyka stanu Chrome - viewport, cookies, itp."""
import asyncio
import json
import urllib.request
import websockets

CDP_HOST = "192.168.128.7"
CDP_PORT = 9223

msg_id = 0
def next_id():
    global msg_id
    msg_id += 1
    return msg_id

async def cdp(ws, method, params=None):
    mid = next_id()
    msg = {"id": mid, "method": method}
    if params:
        msg["params"] = params
    await ws.send(json.dumps(msg))
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        data = json.loads(raw)
        if data.get("id") == mid:
            return data

async def main():
    req = urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json")
    targets = json.loads(req.read())
    
    ws_url = None
    current_url = None
    for t in targets:
        if t.get("type") == "page":
            ws_url = t.get("webSocketDebuggerUrl")
            current_url = t.get("url")
            break
    
    print(f"Target URL: {current_url}")
    
    async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
        # 1. Viewport i rozmiar okna
        metrics = await cdp(ws, "Runtime.evaluate", {
            "expression": """JSON.stringify({
                innerWidth: window.innerWidth,
                innerHeight: window.innerHeight,
                outerWidth: window.outerWidth,
                outerHeight: window.outerHeight,
                screenWidth: screen.width,
                screenHeight: screen.height,
                devicePixelRatio: window.devicePixelRatio,
                userAgent: navigator.userAgent.substring(0, 100),
                webdriver: navigator.webdriver,
                cookieEnabled: navigator.cookieEnabled,
                cookieCount: document.cookie.split(';').filter(c => c.trim()).length
            })""",
            "returnByValue": True
        })
        val = json.loads(metrics.get("result", {}).get("result", {}).get("value", "{}"))
        print(f"\nViewport: {val.get('innerWidth')}x{val.get('innerHeight')}")
        print(f"Outer: {val.get('outerWidth')}x{val.get('outerHeight')}")
        print(f"Screen: {val.get('screenWidth')}x{val.get('screenHeight')}")
        print(f"DPR: {val.get('devicePixelRatio')}")
        print(f"UA: {val.get('userAgent')}")
        print(f"Webdriver: {val.get('webdriver')}")
        print(f"Cookies: {val.get('cookieEnabled')}, count={val.get('cookieCount')}")
        
        # 2. Allegro-specific cookies
        cookies = await cdp(ws, "Runtime.evaluate", {
            "expression": "document.cookie",
            "returnByValue": True
        })
        cookie_str = cookies.get("result", {}).get("result", {}).get("value", "")
        cookie_names = [c.split("=")[0].strip() for c in cookie_str.split(";") if c.strip()]
        print(f"\nAllegro cookies: {cookie_names[:20]}")
        
        # 3. Ile addScriptToEvaluateOnNewDocument jest zarejestrowanych
        # (nie ma na to CDP metody, ale sprawdzimy __ioPatchApplied)
        check = await cdp(ws, "Runtime.evaluate", {
            "expression": "JSON.stringify({ioPatch: !!window.__ioPatchApplied, title: document.title, url: location.href})",
            "returnByValue": True
        })
        val = json.loads(check.get("result", {}).get("result", {}).get("value", "{}"))
        print(f"\nAktualny stan: {val}")
        
        # 4. Sprawdz ilość dialogow i ich zawartosc na aktualnej stronie
        dialogs = await cdp(ws, "Runtime.evaluate", {
            "expression": r"""(function() {
                var ds = document.querySelectorAll("[role='dialog']");
                var r = [];
                for (var i = 0; i < ds.length; i++) {
                    var t = (ds[i].innerText || '').trim();
                    if (t.length > 0) r.push({i: i, len: t.length, t: t.substring(0, 100)});
                }
                return JSON.stringify({total: ds.length, nonEmpty: r.length, sample: r.slice(0, 5)});
            })()""",
            "returnByValue": True
        })
        val = json.loads(dialogs.get("result", {}).get("result", {}).get("value", "{}"))
        print(f"\nDialogi: total={val.get('total')}, nonEmpty={val.get('nonEmpty')}")
        for d in val.get("sample", []):
            print(f"  #{d['i']}: ({d['len']} chars) {d['t'][:80]}")

asyncio.run(main())
