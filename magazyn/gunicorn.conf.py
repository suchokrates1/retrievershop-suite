# gunicorn.conf.py
import os
import fcntl

bind = "0.0.0.0:8000"
workers = 6  # Optimal for N100 (4 cores) with I/O-heavy operations
worker_class = 'sync'  # Standard synchronous worker
timeout = 120  # Worker timeout in seconds
keepalive = 5  # Keep-alive connections
graceful_timeout = 30  # Graceful worker restart timeout


def post_worker_init(worker):
    """Hook called after worker is initialized - start scheduler only in first worker."""
    
    # Use lock file to ensure only ONE worker starts the scheduler
    lock_file = "/tmp/magazyn_scheduler.lock"
    
    try:
        # Try to acquire exclusive lock (non-blocking)
        fd = os.open(lock_file, os.O_CREAT | os.O_WRONLY, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        # If we got here, we acquired the lock - this worker starts the scheduler
        from magazyn.factory import _start_order_sync_scheduler
        from magazyn.price_report_scheduler import start_price_report_scheduler
        from magazyn.factory import _app_instance
        
        _start_order_sync_scheduler()
        worker.log.info(f"Order sync scheduler started in worker {worker.pid}")
        
        # Start price report scheduler
        if _app_instance:
            start_price_report_scheduler(_app_instance)
            worker.log.info(f"Price report scheduler started in worker {worker.pid}")
        
    except (OSError, IOError):
        # Lock already held by another worker - skip scheduler initialization
        worker.log.info(f"Worker {worker.pid} skipped scheduler (already running in another worker)")

