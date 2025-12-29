"""
Allegro Scraper API Server

Simple Flask API that accepts URLs and returns scraped prices.
Runs the scraper_worker.py in the background to check prices.
"""

import os
import sys
import json
import time
import subprocess
import threading
from flask import Flask, request, jsonify
from decimal import Decimal

app = Flask(__name__)

# Global state
scraper_process = None
last_price_check = {}
PRICE_CACHE_TIMEOUT = 300  # 5 minutes

def start_scraper_worker():
    """Start the scraper worker in background"""
    global scraper_process

    if scraper_process and scraper_process.poll() is None:
        return  # Already running

    try:
        # Start scraper_worker.py with --api mode
        scraper_process = subprocess.Popen([
            sys.executable, "scraper_worker.py", "--api"
        ], cwd=os.path.dirname(__file__),
           stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        print("Scraper worker started")
    except Exception as e:
        print(f"Failed to start scraper worker: {e}")

@app.route('/check_price', methods=['GET'])
def check_price():
    """Check price for a given Allegro URL"""
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "Missing 'url' parameter"}), 400

    # Check cache first
    if url in last_price_check:
        timestamp, price = last_price_check[url]
        if time.time() - timestamp < PRICE_CACHE_TIMEOUT:
            return jsonify({"price": price})

    # Start worker if not running
    if not scraper_process or scraper_process.poll() is not None:
        start_scraper_worker()
        # Wait a bit for worker to start
        time.sleep(2)

    # For now, return a mock response
    # In real implementation, this would communicate with the worker
    mock_price = "159.99"
    last_price_check[url] = (time.time(), mock_price)

    return jsonify({"price": mock_price})

@app.route('/status', methods=['GET'])
def status():
    """Get scraper status"""
    worker_running = scraper_process and scraper_process.poll() is None
    return jsonify({
        "worker_running": worker_running,
        "cached_prices": len(last_price_check)
    })

@app.route('/health', methods=['GET'])
def health():
    """Health check"""
    return jsonify({"status": "ok"})

if __name__ == '__main__':
    print("Starting Allegro Scraper API Server...")
    print("Make sure scraper_worker.py is in the same directory")

    # Start worker on startup
    start_scraper_worker()

    # Run Flask app
    app.run(host='0.0.0.0', port=5555, debug=False)