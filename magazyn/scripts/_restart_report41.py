"""Restart raportu #41 po naprawie ofert Cordura."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from magazyn.factory import create_app
app = create_app()

with app.app_context():
    from magazyn.price_report_scheduler import restart_price_report
    result = restart_price_report(41)
    print(f"Restart result: {result}")
