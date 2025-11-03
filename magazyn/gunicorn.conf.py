# gunicorn.conf.py
bind = "0.0.0.0:8000"
worker_class = 'gevent'
timeout = 300
