#!/usr/bin/env python3
"""Test scrapingu cen konkurencji z Allegro przez CDP"""
import asyncio
import json
import websockets
import urllib.request

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222

async def main():
    with urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json") as resp:
        pages = json.loads(resp.read())
    
    main_page = None
    for p in pages:
        if p["type"] == "page":
            main_page = p
            break
    
    ws_url = main_page["webSocketDebuggerUrl"]
    
    async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": """
                (function() {
                    const dialog = document.querySelector("[role='dialog']");
                    if (!dialog) return JSON.stringify({error: "Brak dialogu"});
                    
                    const pricePattern = /([0-9]+(?:,[0-9]{2})?)\\s*zł/;
                    const offers = [];
                    const links = dialog.querySelectorAll("a[href*='/oferta/']");
                    
                    links.forEach(link => {
                        let container = link.closest("article") || link.parentElement.parentElement.parentElement;
                        const text = container.innerText;
                        const priceMatch = text.match(pricePattern);
                        const sellerLink = container.querySelector("a[href*='/uzytkownik/']");
                        const seller = sellerLink ? sellerLink.innerText : "?";
                        const deliveryMatch = text.match(/dostawa[^0-9]*([0-9]+(?:,[0-9]{2})?)/i);
                        
                        if (priceMatch) {
                            offers.push({
                                price: priceMatch[1],
                                seller: seller,
                                delivery: deliveryMatch ? deliveryMatch[1] : "?",
                                href: link.href
                            });
                        }
                    });
                    
                    const unique = [];
                    const seen = new Set();
                    offers.forEach(o => {
                        if (!seen.has(o.href)) {
                            seen.add(o.href);
                            unique.push(o);
                        }
                    });
                    
                    return JSON.stringify({cnt: unique.length, offers: unique.slice(0, 15)});
                })()
            """,
            "returnByValue": True
        }}))
        resp = await ws.recv()
        result = json.loads(resp)
        data_str = result.get("result", {}).get("result", {}).get("value", "{}")
        data = json.loads(data_str)
        
        if "error" in data:
            print(f"Blad: {data['error']}")
        else:
            cnt = data["cnt"]
            print(f"Znaleziono {cnt} ofert konkurencji:")
            for i, o in enumerate(data["offers"], 1):
                seller = o["seller"]
                price = o["price"]
                delivery = o["delivery"]
                print(f"{i}. {seller}: {price} zl + {delivery} dostawa")

if __name__ == "__main__":
    asyncio.run(main())
