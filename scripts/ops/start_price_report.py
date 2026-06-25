#!/usr/bin/env python3
"""Uruchom nowy raport cenowy (tryb szybki) na produkcji."""
from __future__ import annotations

from magazyn.factory import create_app
from magazyn.price_report_scheduler import start_price_report_now


def main() -> None:
    app = create_app()
    with app.app_context():
        report_id = start_price_report_now()
        print(f"OK: uruchomiono raport #{report_id}")


if __name__ == "__main__":
    main()
