#!/bin/sh
pip install -r magazyn/requirements.txt
PYTHONPATH=. pytest -q "$@"
