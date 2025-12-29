# gunicorn.conf.py
bind = "0.0.0.0:8000"
workers = 2  # Number of worker processes
worker_class = 'sync'  # Standard synchronous worker
timeout = 120  # Worker timeout in seconds
keepalive = 5  # Keep-alive connections
graceful_timeout = 30  # Graceful worker restart timeout
