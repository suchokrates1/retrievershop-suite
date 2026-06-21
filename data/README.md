# Katalog `data/` (wolumen Docker)

Montowany jako `/app/data` w kontenerze `retrievershop-magazyn`.

Typowe pliki **tylko na serwerze** (nie w git):

- `incident_invoice_corrections.json` — stan korekt wFirma po skrypcie `scripts/ops/correct_incident_invoices.py`

Nie trzymaj tu starych kopii SQLite (`database.db`, `magazyn.db`) — produkcja używa PostgreSQL.
