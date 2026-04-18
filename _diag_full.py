"""Pelna diagnostyka z IO patch + monitoring sieci."""
import asyncio
import json
import urllib.request
import websockets

CDP_HOST = "192.168.128.7"
CDP_PORT = 9223
OFFER_URL = "https://allegro.pl/oferta/szelki-guard-truelove-18195227579"

IO_PATCH_JS = r"""(function() {
    if (window.__ioPatchApplied) return;
    window.__ioPatchApplied = true;
    Object.defineProperty(navigator, 'webdriver', {get: function() { return false; }});
    var OrigIO = IntersectionObserver;
    window.IntersectionObserver = function(callback, options) {
        var modifiedCallback = function(entries, observer) {
            var fakeEntries = entries.map(function(entry) {
                return {
                    boundingClientRect: entry.boundingClientRect,
                    intersectionRatio: 1.0,
                    intersectionRect: entry.boundingClientRect,
                    isIntersecting: true,
                    rootBounds: entry.rootBounds,
                    target: entry.target,
                    time: entry.time
                };
            });
            callback(fakeEntries, observer);
        };
        var obs = new OrigIO(modifiedCallback, options);
        return obs;
    };
    window.IntersectionObserver.prototype = OrigIO.prototype;
})();"""

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
    for t in targets:
        if t.get("type") == "page":
            ws_url = t.get("webSocketDebuggerUrl")
            break
    
    if not ws_url:
        print("Brak targetu page!")
        return
    
    async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
        await cdp(ws, "Page.enable")
        await cdp(ws, "Network.enable")
        
        # IO patch
        await cdp(ws, "Page.addScriptToEvaluateOnNewDocument", {"source": IO_PATCH_JS})
        
        # about:blank + drain
        await cdp(ws, "Page.navigate", {"url": "about:blank"})
        await asyncio.sleep(0.3)
        while True:
            try:
                await asyncio.wait_for(ws.recv(), timeout=0.2)
            except asyncio.TimeoutError:
                break
        
        # Nawiguj
        await cdp(ws, "Page.navigate", {"url": OFFER_URL})
        print("Nawigacja...")
        
        # Zbieraj WSZYSTKIE XHR/Fetch requesty
        all_requests = []
        start = asyncio.get_event_loop().time()
        load_fired = False
        dialog_time = None
        
        while asyncio.get_event_loop().time() - start < 25:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=0.5)
                data = json.loads(raw)
                
                if data.get("method") == "Page.loadEventFired":
                    load_fired = True
                    print(f"Load event po {asyncio.get_event_loop().time() - start:.1f}s")
                
                if data.get("method") == "Network.requestWillBeSent":
                    req_data = data.get("params", {})
                    url = req_data.get("request", {}).get("url", "")
                    req_type = req_data.get("type", "?")
                    # Filtruj statyczne assety (js, css, img, font)
                    skip = any(url.endswith(ext) for ext in ['.js', '.css', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.woff', '.woff2', '.ttf'])
                    if not skip and not url.startswith('data:'):
                        elapsed = asyncio.get_event_loop().time() - start
                        all_requests.append(f"[{elapsed:.1f}s] [{req_type}] {url[:250]}")
                
            except asyncio.TimeoutError:
                # Co 2s sprawdz dialog
                if load_fired and not dialog_time:
                    check = await cdp(ws, "Runtime.evaluate", {
                        "expression": """(function() {
                            var ds = document.querySelectorAll("[role='dialog']");
                            for (var d of ds) {
                                if (d.innerText && d.innerText.includes('Inne oferty produktu'))
                                    return {found: true, articles: d.querySelectorAll('article').length};
                            }
                            return {found: false, dialogs: ds.length};
                        })()""",
                        "returnByValue": True
                    })
                    val = check.get("result", {}).get("result", {}).get("value", {})
                    if val.get("found"):
                        dialog_time = asyncio.get_event_loop().time() - start
                        print(f"Dialog znaleziony po {dialog_time:.1f}s, articles={val.get('articles')}")
        
        # Diagnostyka
        print(f"\nLoad event: {load_fired}")
        print(f"Dialog: {'tak' if dialog_time else 'nie'}")
        print(f"\nNon-static requesty ({len(all_requests)}):")
        for r in all_requests[:40]:
            print(f"  {r}")
        
        # Koncowa diagnostyka dialogu
        diag = await cdp(ws, "Runtime.evaluate", {
            "expression": """(function() {
                var ds = document.querySelectorAll("[role='dialog']");
                var target = null;
                for (var d of ds) {
                    if (d.innerText && d.innerText.includes('Inne oferty produktu')) {
                        target = d; break;
                    }
                }
                if (!target) return {dialog: false, dialogCount: ds.length, webdriver: navigator.webdriver};
                return {
                    dialog: true,
                    webdriver: navigator.webdriver,
                    articles: target.querySelectorAll('article').length,
                    lazy: target.querySelectorAll('.lazyload').length,
                    loaded: target.querySelectorAll('.lazyloaded').length,
                    htmlLen: target.innerHTML.length,
                    visible: target.offsetParent !== null,
                    display: window.getComputedStyle(target).display,
                    boxes: Array.from(target.querySelectorAll('[data-box-name]')).map(function(e) {
                        return e.getAttribute('data-box-name');
                    }).slice(0, 15)
                };
            })()""",
            "returnByValue": True
        })
        val = diag.get("result", {}).get("result", {}).get("value", {})
        print(f"\nKoncowa diagnostyka: {json.dumps(val, indent=2, ensure_ascii=False)}")

asyncio.run(main())
