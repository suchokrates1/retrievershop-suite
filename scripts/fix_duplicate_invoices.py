"""
Skrypt do weryfikacji i korekty zduplikowanych faktur w wFirma.

Dotyczy 3 zamowien gdzie wystawiono podwojne faktury:
1. allegro_4cebf7a0 (Pawel Chaber) - FBV 174/2026 OK, FBV 177/2026 do korekty
2. allegro_1895c490 (Tomasz Lazar) - FBV 175/2026 OK, FBV 176/2026 do korekty
3. allegro_77e2c190 (Maciej Grabski) - FBV 195/2026 OK, FBV 196/2026 do korekty

Uruchomienie:
  cd /home/suchokrates1/retrievershop-suite
  docker compose exec magazyn python -m scripts.fix_duplicate_invoices [--execute]

Bez --execute: tylko weryfikacja (dry-run).
Z --execute: wystawia korekty zerujace w wFirma.
"""
import sys
import os

# Dodaj root projektu do PYTHONPATH
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from magazyn.factory import create_app

app = create_app()

# Faktury do korekty: (order_id, wfirma_id_OK, wfirma_id_do_korekty, klient)
DUPLICATES = [
    {
        "order_id": "allegro_4cebf7a0-2855-11f1-926e-756b2824c5b4",
        "klient": "Pawel Chaber",
        "faktura_ok_id": 525180213,
        "faktura_ok_nr": "FBV 174/2026",
        "faktura_dup_id": 525194549,
        "faktura_dup_nr": "FBV 177/2026",
    },
    {
        "order_id": "allegro_1895c490-28eb-11f1-8c1b-5d91a0fd7e32",
        "klient": "Tomasz Lazar",
        "faktura_ok_id": 525180277,
        "faktura_ok_nr": "FBV 175/2026",
        "faktura_dup_id": 525180341,
        "faktura_dup_nr": "FBV 176/2026",
    },
    {
        "order_id": "allegro_77e2c190-3012-11f1-a44a-4fcf11fe14a8",
        "klient": "Maciej Grabski",
        "faktura_ok_id": 532541685,
        "faktura_ok_nr": "FBV 195/2026",
        "faktura_dup_id": 532550773,
        "faktura_dup_nr": "FBV 196/2026",
    },
]


def verify_invoices(client):
    """Pobierz i zweryfikuj obie faktury dla kazdego zamowienia."""
    from magazyn.wfirma_api import get_invoice

    all_ok = True
    for dup in DUPLICATES:
        print(f"\n{'='*60}")
        print(f"Zamowienie: {dup['order_id']}")
        print(f"Klient: {dup['klient']}")

        for label, inv_id, inv_nr in [
            ("OK", dup["faktura_ok_id"], dup["faktura_ok_nr"]),
            ("DUPLIKAT", dup["faktura_dup_id"], dup["faktura_dup_nr"]),
        ]:
            try:
                inv = get_invoice(client, inv_id)
                actual_nr = inv.get("fullnumber", "?")
                total = inv.get("total", "?")
                inv_type = inv.get("type", "?")
                status = inv.get("status", "?")

                match = "OK" if inv_nr in actual_nr or actual_nr in inv_nr else "NIEZGODNOSC!"
                print(f"  [{label}] id={inv_id}: {actual_nr} (total={total}, type={inv_type}, status={status}) [{match}]")

                if match == "NIEZGODNOSC!":
                    print(f"    UWAGA: Oczekiwano '{inv_nr}', znaleziono '{actual_nr}'")
                    all_ok = False

                # Sprawdz pozycje
                contents = inv.get("invoicecontents", {})
                for k in sorted(contents):
                    if k == "parameters":
                        continue
                    c = contents[k].get("invoicecontent", {})
                    if c:
                        print(f"    - {c.get('name', '?')}: {c.get('count', '?')} x {c.get('price', '?')} PLN")

            except Exception as e:
                print(f"  [{label}] id={inv_id}: BLAD - {e}")
                all_ok = False

    return all_ok


def create_corrections(client):
    """Wystaw korekty zerujace dla duplikatow."""
    from magazyn.wfirma_api import create_correction_invoice

    results = []
    for dup in DUPLICATES:
        print(f"\nWystawiam korekte zerujaca do {dup['faktura_dup_nr']} (id={dup['faktura_dup_id']})...")
        print(f"  Klient: {dup['klient']}, zamowienie: {dup['order_id']}")

        try:
            result = create_correction_invoice(
                client,
                original_invoice_id=dup["faktura_dup_id"],
                corrected_items=None,  # Korekta zerujaca - wszystkie pozycje na 0
                description=f"Korekta zerujaca - duplikat faktury {dup['faktura_dup_nr']} do zamowienia {dup['order_id']}",
            )
            print(f"  Utworzono korekte: {result['invoice_number']} (id={result['invoice_id']}, total={result['total']})")
            results.append({"dup": dup, "correction": result, "success": True})
        except Exception as e:
            print(f"  BLAD: {e}")
            results.append({"dup": dup, "error": str(e), "success": False})

    return results


def main():
    execute = "--execute" in sys.argv

    with app.app_context():
        from magazyn.wfirma_api import WFirmaClient
        client = WFirmaClient.from_settings()

        print("=" * 60)
        print("WERYFIKACJA DUPLIKATOW FAKTUR W WFIRMA")
        print("=" * 60)

        ok = verify_invoices(client)

        if not ok:
            print("\n!!! Weryfikacja wykazala niezgodnosci - przerwano.")
            sys.exit(1)

        print("\n" + "=" * 60)
        if not execute:
            print("DRY RUN - aby wystawic korekty, uruchom z --execute")
            print("=" * 60)
            sys.exit(0)

        print("WYSTAWIANIE KOREKT ZERUJACYCH")
        print("=" * 60)

        results = create_corrections(client)

        print("\n" + "=" * 60)
        print("PODSUMOWANIE")
        print("=" * 60)
        for r in results:
            status = "OK" if r["success"] else "BLAD"
            dup = r["dup"]
            if r["success"]:
                print(f"  [{status}] {dup['faktura_dup_nr']} -> korekta {r['correction']['invoice_number']}")
            else:
                print(f"  [{status}] {dup['faktura_dup_nr']} -> {r['error']}")


if __name__ == "__main__":
    main()
