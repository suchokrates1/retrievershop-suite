"""Dump zawartosci WSZYSTKICH dialogow na stronie."""
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
    
    async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
        await cdp(ws, "Page.enable")
        
        # IO patch
        add_script = await cdp(ws, "Page.addScriptToEvaluateOnNewDocument", {"source": IO_PATCH_JS})
        io_id = add_script.get("result", {}).get("identifier")
        
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
        
        # Czekaj na load
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            data = json.loads(raw)
            if data.get("method") == "Page.loadEventFired":
                break
        
        print("Load OK")
        
        # Tytul + URL
        info = await cdp(ws, "Runtime.evaluate", {
            "expression": "JSON.stringify({title: document.title, url: location.href})",
            "returnByValue": True
        })
        print(f"Strona: {info.get('result',{}).get('result',{}).get('value','?')}")
        
        # Czekaj 5s zeby dialog sie wyrenderowaly
        await asyncio.sleep(5)
        
        # Dump WSZYSTKICH dialogow
        dump = await cdp(ws, "Runtime.evaluate", {
            "expression": r"""(function() {
                var ds = document.querySelectorAll("[role='dialog']");
                var result = [];
                for (var i = 0; i < ds.length; i++) {
                    var d = ds[i];
                    var text = (d.innerText || '').trim();
                    if (text.length > 0) {
                        result.push({
                            idx: i,
                            textLen: text.length,
                            text: text.substring(0, 200),
                            htmlLen: d.innerHTML.length,
                            lazy: d.querySelectorAll('.lazyload').length,
                            loaded: d.querySelectorAll('.lazyloaded').length,
                            articles: d.querySelectorAll('article').length,
                            boxes: Array.from(d.querySelectorAll('[data-box-name]')).map(function(e) {
                                return e.getAttribute('data-box-name');
                            }).slice(0, 8),
                            hasInneOferty: text.includes('Inne oferty produktu'),
                            visible: d.offsetWidth > 0 && d.offsetHeight > 0,
                            rect: {x: d.getBoundingClientRect().x, y: d.getBoundingClientRect().y, w: d.getBoundingClientRect().width, h: d.getBoundingClientRect().height}
                        });
                    }
                }
                return {
                    total: ds.length,
                    nonEmpty: result.length,
                    ioPatch: !!window.__ioPatchApplied,
                    webdriver: navigator.webdriver,
                    dialogs: result
                };
            })()""",
            "returnByValue": True
        })
        val = dump.get("result", {}).get("result", {}).get("value", {})
        
        print(f"\nDialogi: {val.get('total')} total, {val.get('nonEmpty')} z trescia")
        print(f"IO patch: {val.get('ioPatch')}, webdriver: {val.get('webdriver')}")
        
        for d in val.get("dialogs", []):
            print(f"\n--- Dialog #{d['idx']} ---")
            print(f"  Text ({d['textLen']} chars): {d['text'][:150]}")
            print(f"  HTML: {d['htmlLen']}, lazy: {d['lazy']}, loaded: {d['loaded']}, articles: {d['articles']}")
            print(f"  Boxes: {d.get('boxes', [])}")
            print(f"  Inne oferty: {d['hasInneOferty']}, visible: {d['visible']}, rect: {d.get('rect',{})}")
        
        # Poczekaj jeszcze 10s i sprawdz ponownie
        print("\n\nCzekam 10s na dodatkowy rendering...")
        await asyncio.sleep(10)
        
        dump2 = await cdp(ws, "Runtime.evaluate", {
            "expression": r"""(function() {
                var ds = document.querySelectorAll("[role='dialog']");
                for (var i = 0; i < ds.length; i++) {
                    var d = ds[i];
                    if (d.innerText && d.innerText.includes('Inne oferty produktu')) {
                        return {
                            found: true, idx: i,
                            articles: d.querySelectorAll('article').length,
                            lazy: d.querySelectorAll('.lazyload').length,
                            loaded: d.querySelectorAll('.lazyloaded').length,
                            htmlLen: d.innerHTML.length
                        };
                    }
                }
                // Sprawdz czy jakis dialog ma wiecej tresci
                var biggest = {idx: -1, textLen: 0};
                for (var i = 0; i < ds.length; i++) {
                    var tl = (ds[i].innerText || '').length;
                    if (tl > biggest.textLen) {
                        biggest = {idx: i, textLen: tl, text: ds[i].innerText.substring(0, 300)};
                    }
                }
                return {found: false, biggest: biggest};
            })()""",
            "returnByValue": True
        })
        val2 = dump2.get("result", {}).get("result", {}).get("value", {})
        print(f"Po 10s: {json.dumps(val2, indent=2, ensure_ascii=False)}")
        
        # Cleanup
        if io_id:
            try:
                await cdp(ws, "Page.removeScriptToEvaluateOnNewDocument", {"identifier": io_id})
            except Exception:
                pass

asyncio.run(main())
