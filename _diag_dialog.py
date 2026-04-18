"""Diagnostyka zawartosci dialogu 'Inne oferty produktu'."""
import asyncio
import json
import websockets

CDP_HOST = "192.168.128.7"
CDP_PORT = 9223
OFFER_URL = "https://allegro.pl/oferta/smycz-tradycyjna-retriever-shop-17841931902"

IO_PATCH_JS = r"""(function() {
    if (window.__ioPatchApplied) return;
    window.__ioPatchApplied = true;
    const OrigIO = window.IntersectionObserver;
    window.IntersectionObserver = function(cb, opts) {
        const obs = new OrigIO(function(entries, observer) {
            const faked = entries.map(e => ({
                target: e.target, isIntersecting: true,
                intersectionRatio: 1, boundingClientRect: e.boundingClientRect,
                intersectionRect: e.boundingClientRect,
                rootBounds: e.rootBounds, time: e.time
            }));
            cb(faked, observer);
        }, opts);
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
    # Pobierz target
    import urllib.request
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
        # IO patch
        await cdp(ws, "Page.enable")
        await cdp(ws, "Page.addScriptToEvaluateOnNewDocument", {"source": IO_PATCH_JS})
        
        # about:blank + drain
        await cdp(ws, "Page.navigate", {"url": "about:blank"})
        await asyncio.sleep(0.3)
        while True:
            try:
                await asyncio.wait_for(ws.recv(), timeout=0.2)
            except asyncio.TimeoutError:
                break
        
        # Nawiguj do oferty
        await cdp(ws, "Page.navigate", {"url": OFFER_URL})
        print("Nawigacja...")
        
        # Czekaj na load
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            data = json.loads(raw)
            if data.get("method") == "Page.loadEventFired":
                break
        
        await asyncio.sleep(3)
        
        # Diagnostyka strony
        page_info = await cdp(ws, "Runtime.evaluate", {
            "expression": """(function() {
                return {
                    title: document.title,
                    url: location.href,
                    dialogs: document.querySelectorAll("[role='dialog']").length,
                    bodyLen: document.body.innerHTML.length,
                    bodyText: document.body.innerText.substring(0, 300)
                };
            })()""",
            "returnByValue": True
        })
        pv = page_info.get("result", {}).get("result", {}).get("value", {})
        print(f"Strona: title={pv.get('title','?')}, dialogi={pv.get('dialogs',0)}, bodyLen={pv.get('bodyLen',0)}")
        print(f"URL: {pv.get('url','?')}")
        print(f"Body text: {pv.get('bodyText','?')[:200]}")
        
        print("Czekam na dialog...")
        
        # Czekaj na dialog 'Inne oferty produktu'
        for i in range(20):
            check = await cdp(ws, "Runtime.evaluate", {
                "expression": """(function() {
                    var ds = document.querySelectorAll("[role='dialog']");
                    for (var d of ds) {
                        if (d.innerText && d.innerText.includes('Inne oferty produktu'))
                            return true;
                    }
                    return false;
                })()""",
                "returnByValue": True
            })
            if check.get("result", {}).get("result", {}).get("value"):
                print(f"Dialog znaleziony po {i+1}s")
                break
            await asyncio.sleep(1)
        else:
            print("Dialog nie pojawil sie!")
            return
        
        # Reposition dialogu
        await cdp(ws, "Runtime.evaluate", {
            "expression": """(function() {
                var ds = document.querySelectorAll("[role='dialog']");
                for (var d of ds) {
                    if (d.innerText && d.innerText.includes('Inne oferty produktu')) {
                        d.style.cssText = 'position: fixed !important; left: 0 !important; top: 0 !important; width: 768px !important; min-height: 100vh !important; z-index: 999999 !important; overflow: auto !important;';
                        return true;
                    }
                }
                return false;
            })()""",
            "returnByValue": True
        })
        
        await asyncio.sleep(7)
        
        # Diagnostyka - pełna analiza zawartosci dialogu
        diag = await cdp(ws, "Runtime.evaluate", {
            "expression": r"""(function() {
                var ds = document.querySelectorAll("[role='dialog']");
                var target = null;
                for (var d of ds) {
                    if (d.innerText && d.innerText.includes('Inne oferty produktu')) {
                        target = d;
                        break;
                    }
                }
                if (!target) return {found: false};
                
                // Info o lazy elementach
                var lazyEls = target.querySelectorAll('.lazyload');
                var lazyInfo = Array.from(lazyEls).map(function(el) {
                    return {
                        tag: el.tagName,
                        boxName: el.getAttribute('data-box-name'),
                        protoId: el.getAttribute('data-prototype-id'),
                        role: el.getAttribute('data-role'),
                        cls: el.className.substring(0, 100),
                        childCount: el.children.length,
                        rect: el.getBoundingClientRect().toJSON()
                    };
                });
                
                // Opbox-offers-list
                var offerLists = target.querySelectorAll('[data-role="opbox-offers-list"]');
                var listInfo = Array.from(offerLists).map(function(el) {
                    return {
                        cls: el.className.substring(0, 100),
                        childCount: el.children.length,
                        htmlLen: el.innerHTML.length
                    };
                });
                
                // ProductOffersListingContainer
                var plc = target.querySelector('[data-box-name="ProductOffersListingContainer"]');
                
                // Struktura glowna - jakie data-box-name sa w dialogu
                var boxes = target.querySelectorAll('[data-box-name]');
                var boxNames = Array.from(boxes).map(function(el) {
                    return el.getAttribute('data-box-name') + '(' + el.className.substring(0, 30) + ')';
                });
                
                // Czy lazySizes jest dostepny
                var hasLazySizes = typeof window.lazySizes !== 'undefined';
                
                // Text content (skrocony)
                var text = target.innerText.substring(0, 500);
                
                return {
                    found: true,
                    htmlLen: target.innerHTML.length,
                    lazyCount: lazyEls.length,
                    lazyInfo: lazyInfo,
                    loadedCount: target.querySelectorAll('.lazyloaded').length,
                    articles: target.querySelectorAll('article').length,
                    container: !!plc,
                    offerLists: listInfo,
                    boxNames: boxNames,
                    hasLazySizes: hasLazySizes,
                    ioPatch: !!window.__ioPatchApplied,
                    text: text
                };
            })()""",
            "returnByValue": True
        })
        
        val = diag.get("result", {}).get("result", {}).get("value", {})
        print(json.dumps(val, indent=2, ensure_ascii=False))

asyncio.run(main())
