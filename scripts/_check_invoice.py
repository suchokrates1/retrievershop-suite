from magazyn.factory import create_app
from magazyn.db import get_session
from magazyn.models import PurchaseBatch
app = create_app()
with app.app_context():
    with get_session() as db:
        count = db.query(PurchaseBatch).filter_by(invoice_number='2026/04/000182').count()
        print(f'Batche z faktury 2026/04/000182: {count}')
