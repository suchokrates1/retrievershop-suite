"""Diagnostyka strony Allegro - sprawdzam czy jest captcha lub ochrona."""
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
    current_url = "(nieznany)"
    for page in pages:
        if page.get("type") == "page" and "devtools" not in page.get("url", "").lower():
            ws_url = page["webSocketDebuggerUrl"]
            current_url = page.get("url", "")
            break
    
    print(f"Aktualny URL: {current_url}")
    
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
        
        # Sprawdz captcha / access denied
        js = r'''(function() {
            var body = document.body;
            if (!body) return {error: "no body"};
            var text = body.innerText;
            
            // Captcha indicators
            var hasCaptcha = text.includes("captcha") || text.includes("CAPTCHA") || 
                            text.includes("robot") || text.includes("weryfikacja") ||
                            document.querySelector('iframe[src*="captcha"]') !== null ||
                            document.querySelector('[class*="captcha"]') !== null;
            
            // Access denied
            var accessDenied = text.includes("Access Denied") || text.includes("403") ||
                              text.includes("Blokada") || text.includes("blocked");
            
            // Ile dialogow
            var dialogs = document.querySelectorAll("[role='dialog']");
            var dialogInfo = [];
            for (var i = 0; i < dialogs.length; i++) {
                var d = dialogs[i];
                dialogInfo.push({
                    index: i,
                    textLen: d.innerText.length,
                    textFirst200: d.innerText.substring(0, 200),
                    childCount: d.children.length,
                    hasSpinner: d.querySelector('[data-box-name="allegro.spinner"]') !== null,
                    role: d.getAttribute('role'),
                    ariaLabel: d.getAttribute('aria-label')
                });
            }
            
            // Title strony
            var title = document.title;
            
            // Elementy specjalne
            var pageContent = text.substring(0, 1000);
            
            return {
                title: title,
                url: window.location.href,
                hasCaptcha: hasCaptcha,
                accessDenied: accessDenied,
                dialogs: dialogInfo,
                dialogCount: dialogs.length,
                bodyTextLen: text.length,
                pageContentFirst1000: pageContent
            };
        })()'''
        
        result = await cdp("Runtime.evaluate", {
            "expression": js,
            "returnByValue": True
        })
        val = result.get("result", {}).get("result", {}).get("value", {})
        
        print(f"\nTitle: {val.get('title', '?')}")
        print(f"URL: {val.get('url', '?')}")
        print(f"Captcha: {val.get('hasCaptcha', '?')}")
        print(f"Access Denied: {val.get('accessDenied', '?')}")
        print(f"Body text length: {val.get('bodyTextLen', '?')}")
        print(f"Dialogs: {val.get('dialogCount', '?')}")
        
        for d in val.get('dialogs', []):
            print(f"\n--- Dialog {d['index']} ---")
            print(f"  Text length: {d['textLen']}")
            print(f"  Children: {d['childCount']}")
            print(f"  Has spinner: {d['hasSpinner']}")
            print(f"  aria-label: {d.get('ariaLabel')}")
            print(f"  Text: {d['textFirst200']}")
        
        content = val.get('pageContentFirst1000', '')
        print(f"\n--- Strona (1000 first chars) ---")
        print(content[:500])

asyncio.run(main())
