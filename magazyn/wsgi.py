"""WSGI entrypoint for running the magazyn application with Gunicorn."""

from magazyn.factory import create_app

app = create_app()
