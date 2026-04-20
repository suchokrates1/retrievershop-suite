"""Analiza bledu parsowania 5zl - dump artykulow z dialogu."""
import sys
import asyncio
import json
sys.path.insert(0, '/app')
from magazyn.factory import create_app
app = create_app()

with app.app_context():
    from magazyn.scripts.price_checker_ws import (
        get_cdp_websocket_url, navigate_to_url, wait_for_dialog,
        cdp_call, build_offer_url
    )
    import websockets

    async def dump_dialog():
        ws_url = await get_cdp_websocket_url("192.168.31.5", 9223)
        async with websockets.connect(ws_url, max_size=10*1024*1024) as ws:
            url = build_offer_url("18334850404", "Szelki guard M fiolet")
            await navigate_to_url(ws, url)
            if not await wait_for_dialog(ws):
                print("Dialog nie pojawil sie")
                return

            # Dump surowych artykulow
            js = r'''
            (function() {
                const articles = document.querySelectorAll('article');
                let results = [];
                articles.forEach((a, idx) => {
                    const links = [];
                    a.querySelectorAll('a[href]').forEach(l => links.push(l.href));
                    results.push({
                        idx: idx,
                        text: a.innerText.substring(0, 400),
                        links: links.slice(0, 5),
                        html_len: a.innerHTML.length
                    });
                });
                return JSON.stringify(results);
            })()
            '''
            result = await cdp_call(ws, "Runtime.evaluate",
                                    {"expression": js, "returnByValue": True},
                                    msg_id=100)
            val = result.get("result", {}).get("result", {}).get("value", "[]")
            articles = json.loads(val)

            print(f"Znaleziono {len(articles)} artykulow w dialogu:\n")
            for a in articles:
                print(f"--- Article {a['idx']} (html: {a['html_len']} bytes) ---")
                print(f"TEXT: {a['text'][:300]}")
                print(f"LINKS: {a['links']}")
                print()

    asyncio.run(dump_dialog())
