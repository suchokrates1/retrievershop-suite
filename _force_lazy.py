"""Probuje wymusic zaladowanie lazy spinnera roznymi metodami."""
import asyncio
import json
import urllib.request

CDP_HOST = "192.168.128.7"
CDP_PORT = 9223

async def main():
    url = f"http://{CDP_HOST}:{CDP_PORT}/json"
    with urllib.request.urlopen(url, timeout=10) as resp:
        pages = json.loads(resp.read())
    
    ws_url = None
    for page in pages:
        if page.get("type") == "page" and "devtools" not in page.get("url", "").lower():
            ws_url = page["webSocketDebuggerUrl"]
            break
    
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
        
        print("=== Stan poczatkowy ===")
        r = await cdp("Runtime.evaluate", {
            "expression": r'''(function() {
                var all = document.querySelectorAll('.lazyload');
                var info = [];
                for (var i = 0; i < all.length; i++) {
                    info.push({
                        tag: all[i].tagName,
                        box: all[i].getAttribute('data-box-name'),
                        parent: all[i].parentElement ? all[i].parentElement.getAttribute('role') : null,
                        html: all[i].outerHTML.substring(0, 300)
                    });
                }
                // Sprawdz lazySizes
                var hasLazySizes = typeof window.lazySizes !== 'undefined';
                
                // Sprawdz stale IO patches 
                var scriptCount = window.__ioPatchCount || 0;
                
                return {
                    lazyCount: all.length,
                    items: info,
                    hasLazySizes: hasLazySizes,
                    ioPatch: !!window.__ioPatchApplied,
                    patchCount: scriptCount
                };
            })()''',
            "returnByValue": True
        })
        val = r.get("result", {}).get("result", {}).get("value", {})
        print(json.dumps(val, indent=2, ensure_ascii=False))
        
        # Metoda 1: scrollIntoView na wszystkich lazyload
        print("\n=== Metoda 1: scrollIntoView ===")
        r = await cdp("Runtime.evaluate", {
            "expression": r'''(function() {
                var all = document.querySelectorAll('.lazyload');
                all.forEach(function(el) {
                    el.scrollIntoView({behavior: 'instant', block: 'center'});
                });
                return all.length;
            })()''',
            "returnByValue": True
        })
        print(f"scrollIntoView na {r.get('result', {}).get('result', {}).get('value')} elementach")
        await asyncio.sleep(3)
        
        # Sprawdz efekt
        r = await cdp("Runtime.evaluate", {
            "expression": "document.querySelectorAll('.lazyload').length + ' lazy, ' + document.querySelectorAll('.lazyloaded').length + ' loaded'",
            "returnByValue": True
        })
        print(f"Po scrollIntoView: {r.get('result', {}).get('result', {}).get('value')}")
        
        # Metoda 2: zmiana klasy z lazyload na lazyloading
        print("\n=== Metoda 2: class lazyload -> lazyloading ===")
        r = await cdp("Runtime.evaluate", {
            "expression": r'''(function() {
                var all = document.querySelectorAll('.lazyload');
                var count = 0;
                all.forEach(function(el) {
                    el.classList.remove('lazyload');
                    el.classList.add('lazyloading');
                    count++;
                });
                return count;
            })()''',
            "returnByValue": True
        })
        print(f"Zmieniono klase na {r.get('result', {}).get('result', {}).get('value')} elementach")
        await asyncio.sleep(3)
        
        r = await cdp("Runtime.evaluate", {
            "expression": r'''(function() {
                return {
                    lazyload: document.querySelectorAll('.lazyload').length,
                    lazyloading: document.querySelectorAll('.lazyloading').length,
                    lazyloaded: document.querySelectorAll('.lazyloaded').length,
                    articles: document.querySelectorAll('article').length,
                    ariaPrice: document.querySelectorAll('p[aria-label*="aktualna cena"]').length
                };
            })()''',
            "returnByValue": True
        })
        val = r.get("result", {}).get("result", {}).get("value", {})
        print(f"Po zmianie klasy: {json.dumps(val)}")
        
        # Metoda 3: dispatchEvent na elemencie
        print("\n=== Metoda 3: dispatch events ===")
        r = await cdp("Runtime.evaluate", {
            "expression": r'''(function() {
                var all = document.querySelectorAll('.lazyloading');
                all.forEach(function(el) {
                    el.dispatchEvent(new Event('lazybeforeunveil', {bubbles: true}));
                    el.dispatchEvent(new Event('lazyunveilread', {bubbles: true}));
                    el.dispatchEvent(new Event('scroll', {bubbles: true}));
                    el.dispatchEvent(new Event('resize'));
                });
                // Probuj wywolac lazysizes jesli dostepne
                if (window.lazySizes) {
                    window.lazySizes.loader.checkElems();
                }
                return all.length;
            })()''',
            "returnByValue": True
        })
        print(f"Dispatched events na {r.get('result', {}).get('result', {}).get('value')} elementach")
        await asyncio.sleep(3)
        
        # Sprawdz koncowy stan
        print("\n=== Stan koncowy ===")
        r = await cdp("Runtime.evaluate", {
            "expression": r'''(function() {
                // Znajdz dialog "Inne oferty produktu"
                var dialogs = document.querySelectorAll("[role='dialog']");
                var targetDialog = null;
                for (var i = 0; i < dialogs.length; i++) {
                    if (dialogs[i].innerText.includes('Inne oferty produktu')) {
                        targetDialog = dialogs[i];
                        break;
                    }
                }
                
                return {
                    lazyload: document.querySelectorAll('.lazyload').length,
                    lazyloading: document.querySelectorAll('.lazyloading').length,
                    lazyloaded: document.querySelectorAll('.lazyloaded').length,
                    articles: document.querySelectorAll('article').length,
                    ariaPrice: document.querySelectorAll('p[aria-label*="aktualna cena"]').length,
                    targetDialogExists: !!targetDialog,
                    targetDialogText: targetDialog ? targetDialog.innerText.substring(0, 500) : 'nie znaleziono'
                };
            })()''',
            "returnByValue": True
        })
        val = r.get("result", {}).get("result", {}).get("value", {})
        print(json.dumps(val, indent=2, ensure_ascii=False))

asyncio.run(main())
