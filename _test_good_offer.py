"""Sprawdza czy szelki guard TrueLove mają oferty konkurencji na Allegro.
Porownuje z oferta ktora dziala (smycz tradycyjna)."""
import asyncio
import json
import urllib.request

CDP_HOST = "192.168.128.7"
CDP_PORT = 9223

# Oferta ktora DZIALALA w testach
GOOD_OFFER = "17841931902"  # Szelki TrueLove z wycinankami - miala 6 ofert

# Oferta ktora NIE DZIALA 
BAD_OFFER = "17839093574"  # Szelki guard TrueLove Blossom XL

async def main():
    url = f"http://{CDP_HOST}:{CDP_PORT}/json"
    with urllib.request.urlopen(url, timeout=10) as resp:
        pages = json.loads(resp.read())
    
    ws_url = None
    for page in pages:
        if page.get("type") == "page" and "devtools" not in page.get("url", "").lower():
            ws_url = page["webSocketDebuggerUrl"]
            break
    
    if not ws_url:
        print("Nie znaleziono strony w CDP")
        return
    
    import websockets
    
    async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
        msg_id = 1
        
        async def cdp(method, params=None):
            nonlocal msg_id
            req = {"id": msg_id, "method": method}
            if params:
                req["params"] = params
            await ws.send(json.dumps(req))
            while True:
                resp = await ws.recv()
                data = json.loads(resp)
                if data.get("id") == msg_id:
                    msg_id += 1
                    return data
        
        await cdp("Page.enable")
        
        # Test DOBREJ oferty
        print(f"=== Test dobrej oferty: {GOOD_OFFER} ===")
        test_url = f"https://allegro.pl/oferta/x-{GOOD_OFFER}#inne-oferty-produktu"
        print(f"Nawiguje do: {test_url}")
        
        await cdp("Page.navigate", {"url": test_url})
        
        # Czekaj na load
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < 30:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=1)
                data = json.loads(msg)
                if data.get("method") == "Page.loadEventFired":
                    break
            except asyncio.TimeoutError:
                continue
        
        await asyncio.sleep(3)
        
        # Sprawdz dialog
        for attempt in range(15):
            result = await cdp("Runtime.evaluate", {
                "expression": """(function() {
                    var d = document.querySelector("[role='dialog']");
                    if (!d) return null;
                    if (!d.innerText.includes('Inne oferty produktu')) return null;
                    return d.innerHTML.length;
                })()""",
                "returnByValue": True
            })
            val = result.get("result", {}).get("result", {}).get("value")
            if val:
                print(f"Dialog znaleziony po {attempt+1}s (innerHTML: {val} znakow)")
                break
            await asyncio.sleep(1)
        else:
            print("Dialog NIE znaleziony po 15s")
        
        # Pelna diagnostyka dialogu
        diag = await cdp("Runtime.evaluate", {
            "expression": r'''(function() {
                var d = document.querySelector("[role='dialog']");
                if (!d) return {dialog: false};
                
                // Wszystkie data-box-name
                var boxes = [];
                d.querySelectorAll('[data-box-name]').forEach(function(el) {
                    boxes.push({
                        name: el.getAttribute('data-box-name'),
                        cls: el.className.substring(0, 80),
                        children: el.children.length,
                        text: el.innerText.substring(0, 100)
                    });
                });
                
                var lazy = d.querySelectorAll('.lazyload').length;
                var loaded = d.querySelectorAll('.lazyloaded').length;
                var articles = d.querySelectorAll('article').length;
                
                return {
                    dialog: true,
                    lazy: lazy,
                    loaded: loaded,
                    articles: articles,
                    boxes: boxes,
                    dialogTextFirst500: d.innerText.substring(0, 500)
                };
            })()''',
            "returnByValue": True
        })
        val = diag.get("result", {}).get("result", {}).get("value", {})
        print(json.dumps(val, indent=2, ensure_ascii=False))

asyncio.run(main())
