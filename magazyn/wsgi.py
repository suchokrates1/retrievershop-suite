"""WSGI entrypoint for running the magazyn application with Gunicorn."""

import os

from magazyn.factory import create_app
from magazyn.socketio_extension import socketio

app = create_app()

if __name__ == "__main__":
    host = os.environ.get("FLASK_RUN_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_RUN_PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG") == "1"
    socketio.run(app, host=host, port=port, debug=debug)
