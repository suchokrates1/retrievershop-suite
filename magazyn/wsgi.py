"""WSGI entrypoint for running the magazyn application with Gunicorn."""

from magazyn.factory import create_app
from magazyn.socketio_extension import socketio

app = create_app()

if __name__ == "__main__":
    # For development: run with SocketIO
    socketio.run(app, host="0.0.0.0", port=5000, debug=True)
