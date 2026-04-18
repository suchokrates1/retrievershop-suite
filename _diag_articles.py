"""Diagnostyka - co dokladnie jest w dialogu 'Inne oferty produktu'."""
import asyncio
import json
import urllib.request
import websockets

CDP_HOST = "192.168.128.7"
CDP_PORT = 9223
OFFER_URL = "https://allegro.pl/oferta/obroza-dla-psa-truelove-tropical-l-18314193732#inne-oferty-produktu"

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
    ws_url = next(t["webSocketDebuggerUrl"] for t in targets if t.get("type") == "page")
    
    async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
        # Ustaw normalny viewport
        await cdp(ws, "Emulation.setDeviceMetricsOverride", {
            "width": 1920, "height": 1080, "deviceScaleFactor": 1, "mobile": False
        })
        
        await cdp(ws, "Page.enable")
        await cdp(ws, "Page.navigate", {"url": OFFER_URL})
        
        # Czekaj na load
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            data = json.loads(raw)
            if data.get("method") == "Page.loadEventFired":
                break
        
        print(f"Load OK")
        await asyncio.sleep(3)
        
        # Sprawdz status strony
        info = await cdp(ws, "Runtime.evaluate", {
            "expression": "JSON.stringify({title: document.title, url: location.href, hash: location.hash})",
            "returnByValue": True
        })
        val = json.loads(info.get("result", {}).get("result", {}).get("value", "{}"))
        print(f"URL: {val.get('url')}")
        print(f"Hash: {val.get('hash')}")
        
        # Czekaj + sprawdzaj co 2s
        for check in range(8):
            await asyncio.sleep(2)
            t = 3 + (check + 1) * 2
            
            diag = await cdp(ws, "Runtime.evaluate", {
                "expression": r"""(function() {
                    var ds = document.querySelectorAll("[role='dialog']");
                    var results = [];
                    for (var i = 0; i < ds.length; i++) {
                        var d = ds[i];
                        var text = (d.innerText || '').trim();
                        if (text.length > 10) {
                            results.push({
                                idx: i,
                                hasInne: text.includes('Inne oferty produktu'),
                                textLen: text.length,
                                articles: d.querySelectorAll('article').length,
                                htmlLen: d.innerHTML.length,
                                text: text.substring(0, 200)
                            });
                        }
                    }
                    // Sprawdz tez ProductOffersListingContainer na calej stronie
                    var plc = document.querySelector('[data-box-name="ProductOffersListingContainer"]');
                    var plc2 = document.querySelector('[data-box-name="ProductListing Container"]');
                    var allArticles = document.querySelectorAll('article').length;
                    
                    return {
                        totalDialogs: ds.length,
                        nonEmpty: results.length,
                        dialogs: results,
                        plcOnPage: !!plc,
                        plc2OnPage: !!plc2,
                        allArticlesOnPage: allArticles,
                        viewport: {w: window.innerWidth, h: window.innerHeight}
                    };
                })()""",
                "returnByValue": True
            })
            val = diag.get("result", {}).get("result", {}).get("value", {})
            
            articles_total = val.get("allArticlesOnPage", 0)
            non_empty = val.get("nonEmpty", 0)
            vp = val.get("viewport", {})
            
            print(f"\n[{t}s] Viewport: {vp.get('w')}x{vp.get('h')}, dialogi z trescia: {non_empty}, articles na stronie: {articles_total}")
            
            for d in val.get("dialogs", []):
                if d.get("hasInne"):
                    print(f"  Dialog #{d['idx']}: articles={d.get('articles')}, text={d.get('text')[:120]}")
            
            if articles_total > 0:
                print(f"  SUKCES - artykuly znalezione!")
                break
        
        # Koncowa diagnostyka
        final = await cdp(ws, "Runtime.evaluate", {
            "expression": r"""(function() {
                // Sprawdz czy jest captcha
                var body = document.body.innerText;
                var hasCaptcha = body.includes('captcha') || body.includes('CAPTCHA') || body.includes('robot');
                
                // Sprawdz selektor sidebar
                var sidebar = document.querySelector('[data-box-name="sidebar"]');
                var rightColumn = document.querySelector('[data-box-name="rightColumn"]');
                
                // Sprawdz konkretne elementy ofert
                var offersContainer = document.querySelector('[data-role="opbox-offers-list"]');
                
                return {
                    hasCaptcha: hasCaptcha,
                    hasSidebar: !!sidebar,
                    hasRightColumn: !!rightColumn,
                    hasOffersContainer: !!offersContainer,
                    offersContainerClass: offersContainer ? offersContainer.className : null,
                    bodyLen: body.length
                };
            })()""",
            "returnByValue": True
        })
        fv = final.get("result", {}).get("result", {}).get("value", {})
        print(f"\nKoncowa: captcha={fv.get('hasCaptcha')}, sidebar={fv.get('hasSidebar')}, rightColumn={fv.get('hasRightColumn')}")
        print(f"offersContainer={fv.get('hasOffersContainer')}, class={fv.get('offersContainerClass')}")

asyncio.run(main())
