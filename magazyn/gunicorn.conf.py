# gunicorn.conf.py
import os

bind = "0.0.0.0:8000"
workers = 6  # Optimal for N100 (4 cores) with I/O-heavy operations
worker_class = 'sync'  # Standard synchronous worker
timeout = 120  # Worker timeout in seconds
keepalive = 5  # Keep-alive connections
graceful_timeout = 30  # Graceful worker restart timeout

# Flag to track if scheduler started
_scheduler_started = False


def post_worker_init(worker):
    """Hook called after worker is initialized - start scheduler only in first worker."""
    global _scheduler_started
    
    # Only start scheduler in the first worker (worker with lowest PID)
    # This prevents multiple schedulers running simultaneously
    if not _scheduler_started:
        _scheduler_started = True
        
        # Import here to avoid circular imports
        from magazyn.factory import _start_order_sync_scheduler
        from flask import current_app
        
        try:
            _start_order_sync_scheduler()
            worker.log.info(f"Order sync scheduler started in worker {worker.pid}")
        except Exception as e:
            worker.log.error(f"Failed to start scheduler in worker {worker.pid}: {e}")
