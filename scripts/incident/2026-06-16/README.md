# Incydent 16.06.2026 — reverse sync / reprocessing

Skrypty użyte podczas awarii (nadpisanie bazy ze starego Mikrusa, duplikaty etykiet i faktur).

Status na 20.06.2026:
- Korekty wFirma duplikatów FBV 338–371: wykonane (FK 58–90), stan w `data/incident_invoice_corrections.json`
- Duplikaty etykiet: część anulowana przez `cancel_incident_duplicates.py` (Allegro One/InPost bez API cancel)

Nie uruchamiaj ponownie bez edycji list ID w plikach.
