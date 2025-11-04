#!/bin/bash
set -e

echo "Instalowanie zależności..."
pip install -r requirements.txt

echo "Uruchamianie testów..."
PYTHONPATH=. pytest

echo "Uruchamianie aplikacji..."
flask run --host=0.0.0.0 --port=8000
