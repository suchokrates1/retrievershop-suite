# gunicorn.conf.py
bind = "0.0.0.0:8000"
workers = 6  # Optimal for N100 (4 cores) with I/O-heavy operations
worker_class = 'sync'  # Standard synchronous worker
timeout = 120  # Worker timeout in seconds
keepalive = 5  # Keep-alive connections
graceful_timeout = 30  # Graceful worker restart timeout
