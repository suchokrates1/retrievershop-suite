#!/usr/bin/env python3
"""
Simple Chrome Remote Control via CDP WebSocket.
Run this on RPI to provide HTTP interface for viewing and clicking on Chrome.
"""
import json
import base64
import asyncio
import websockets
from aiohttp import web

current_page_id = None
ws_connection = None

async def cdp_handler(websocket):
    global ws_connection
    ws_connection = websocket
    print("CDP WebSocket connected")
    try:
        async for message in websocket:
            data = json.loads(message)
            if data.get('method') == 'Page.screencastFrame':
                # Frame received, acknowledge it
                await websocket.send(json.dumps({
                    'id': data['params']['sessionId'],
                    'method': 'Page.screencastFrameAck',
                    'params': {'sessionId': data['params']['sessionId']}
                }))
    except websockets.exceptions.ConnectionClosed:
        print("CDP WebSocket disconnected")
        ws_connection = None

async def screenshot_handler(request):
    """Get current screenshot"""
    if not ws_connection:
        return web.Response(text="No Chrome connection", status=503)
    
    # Request screenshot via CDP
    await ws_connection.send(json.dumps({
        'id': 1,
        'method': 'Page.captureScreenshot',
        'params': {}
    }))
    
    # Wait for response
    response = await ws_connection.recv()
    data = json.loads(response)
    
    if 'result' in data and 'data' in data['result']:
        img_data = base64.b64decode(data['result']['data'])
        return web.Response(body=img_data, content_type='image/png')
    
    return web.Response(text="Screenshot failed", status=500)

async def click_handler(request):
    """Handle click at x,y coordinates"""
    if not ws_connection:
        return web.json_response({'error': 'No Chrome connection'}, status=503)
    
    data = await request.json()
    x, y = data.get('x', 0), data.get('y', 0)
    
    # Send mousePressed
    await ws_connection.send(json.dumps({
        'id': 2,
        'method': 'Input.dispatchMouseEvent',
        'params': {
            'type': 'mousePressed',
            'x': x,
            'y': y,
            'button': 'left',
            'clickCount': 1
        }
    }))
    
    await asyncio.sleep(0.1)
    
    # Send mouseReleased
    await ws_connection.send(json.dumps({
        'id': 3,
        'method': 'Input.dispatchMouseEvent',
        'params': {
            'type': 'mouseReleased',
            'x': x,
            'y': y,
            'button': 'left',
            'clickCount': 1
        }
    }))
    
    return web.json_response({'status': 'clicked', 'x': x, 'y': y})

async def main():
    # Start HTTP server
    app = web.Application()
    app.router.add_get('/screenshot', screenshot_handler)
    app.router.add_post('/click', click_handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 9223)
    await site.start()
    
    print("HTTP server running on :9223")
    print("Connecting to Chrome CDP...")
    
    # Connect to Chrome CDP WebSocket
    async with websockets.connect('ws://localhost:9222/devtools/page/PLACEHOLDER_PAGE_ID') as websocket:
        # Start screencast
        await websocket.send(json.dumps({
            'id': 0,
            'method': 'Page.startScreencast',
            'params': {'format': 'jpeg', 'quality': 80}
        }))
        
        await cdp_handler(websocket)

if __name__ == '__main__':
    asyncio.run(main())
