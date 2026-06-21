# Skrypty pomocnicze

Uruchamianie (na serwerze, w kontenerze):

```bash
docker cp ~/retrievershop-suite/scripts/ops/audit_wfirma_invoices.py retrievershop-magazyn:/tmp/
docker exec -e PYTHONPATH=/app retrievershop-magazyn python /tmp/audit_wfirma_invoices.py --months 3
```

Lokalnie (z katalogu repo, z `.env`):

```bash
python scripts/ops/audit_unlinked.py
```

## `ops/` — narzędzia wielokrotnego użytku

| Skrypt | Opis |
|--------|------|
| `audit_wfirma_invoices.py` | Audyt duplikatów faktur wFirma vs zamówienia |
| `audit_unlinked.py` | Oferty i pozycje zamówień bez powiązania z magazynem |
| `audit_partial_refunds.py` | Audyt częściowych zwrotów |
| `audit_return_stock.py` | Audyt stocku po zwrotach |
| `backfill_offer_links.py` | Uzupełnianie powiązań ofert |
| `fix_allegro_typos.py` | Naprawa literówek w tytułach ofert |
| `export_orders.py` | Eksport zamówień |
| `sync_allegro_orders.py` | Sync zamówień Allegro |
| `link_manual_shipment.py` | Ręczne powiązanie przesyłki |

## `failover/` — HA magazyn.retrievershop.pl

Deploy na minipc: `bash scripts/failover/deploy-minipc.sh minipc`  
Deploy na VPS: `bash scripts/failover/deploy-vps.sh vps`

## Inne

- `e2e_browser_test.py` — test przeglądarkowy UI

## Ignorowane (nie commituj)

- `scripts/debug/` — tymczasowe debugi
- `scripts/_*.py` — scratch z sesji agenta
- `tmp_deploy/` — na serwerze, stare kopie plików przed deployem
