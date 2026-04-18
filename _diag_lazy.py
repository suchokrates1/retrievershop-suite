"""Diagnostyka lazy elementow w dialogu Allegro."""
import asyncio
import json
import urllib.request

CDP_HOST = "192.168.128.7"
CDP_PORT = 9223

async def main():
    # Pobierz WebSocket URL
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
        
        # Sprawdz aktualny URL
        result = await cdp("Runtime.evaluate", {
            "expression": "window.location.href",
            "returnByValue": True
        })
        current_url = result.get("result", {}).get("result", {}).get("value", "")
        print(f"Aktualny URL: {current_url}")
        
        # Sprawdz lazy elementy w dialogu
        js = r'''(function() {
            var d = document.querySelector("[role='dialog']");
            if (!d) return {dialog: false};
            
            // Wszystkie elementy z class zawierajacym "lazy"
            var lazyEls = d.querySelectorAll('[class*="lazy"]');
            var lazyInfo = [];
            for (var i = 0; i < lazyEls.length; i++) {
                var el = lazyEls[i];
                lazyInfo.push({
                    tag: el.tagName,
                    className: el.className,
                    dataBoxName: el.getAttribute('data-box-name'),
                    childCount: el.children.length,
                    innerHTML: el.innerHTML.substring(0, 500)
                });
            }
            
            // data-box-name elementy
            var boxEls = d.querySelectorAll('[data-box-name]');
            var boxInfo = [];
            for (var i = 0; i < boxEls.length; i++) {
                var el = boxEls[i];
                boxInfo.push({
                    tag: el.tagName,
                    dataBoxName: el.getAttribute('data-box-name'),
                    className: el.className.substring(0, 100),
                    childCount: el.children.length
                });
            }
            
            return {
                dialog: true,
                dialogText: d.innerText.substring(0, 300),
                ioPatch: !!window.__ioPatchApplied,
                lazyElements: lazyInfo,
                boxElements: boxInfo,
                articleCount: d.querySelectorAll('article').length,
                pAriaCount: d.querySelectorAll('p[aria-label]').length
            };
        })()'''
        
        result = await cdp("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True
        })
        val = result.get("result", {}).get("result", {}).get("value", {})
        print(json.dumps(val, indent=2, ensure_ascii=False))

asyncio.run(main())
