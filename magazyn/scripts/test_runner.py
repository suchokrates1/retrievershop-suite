#!/usr/bin/env python3
"""Test runner for scraper - captures output"""
import subprocess
import sys
import time

cmd = [
    sys.executable,
    "scraper_worker.py",
    "--url", "https://magazyn.retrievershop.pl",
    "--proxy", "http://0e7fda9b3495e89f:ktZ7KLWr@res.geonix.com:10000"
]

print("[TEST] Starting scraper...")
proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

try:
    # Read output for 40 seconds
    start = time.time()
    for line in proc.stdout:
        print(line, end='', flush=True)
        if time.time() - start > 40:
            break
finally:
    proc.terminate()
    proc.wait(timeout=5)
    print("\n[TEST] Process terminated")
