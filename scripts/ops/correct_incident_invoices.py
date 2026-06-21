#!/usr/bin/env python3
"""Korekty zerujace duplikatow faktur z incydentu 16.06.2026."""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from magazyn.factory import create_app
from magazyn.wfirma_api.client import WFirmaClient, WFirmaError
from magazyn.wfirma_api.invoices import create_correction_invoice, get_invoice

CORRECTION_REASON = (
    "Korekta zerujaca - duplikat rachunku z incydentu 16.06.2026 (reprocessing)"
)
STATE_FILE = Path("/app/data/incident_invoice_corrections.json")

# Duplikaty z audytu 16.06 — NIE sa w orders.wfirma_invoice_id
INCIDENT_DUPLICATES: list[dict[str, Any]] = [
    {"id": 620447797, "number": "FBV 338/2026", "total": 179.00, "order_suffix": "8e8a-b13312e55057"},
    {"id": 620447861, "number": "FBV 339/2026", "total": 229.00, "order_suffix": "b09e-572fb364178c"},
    {"id": 620448053, "number": "FBV 340/2026", "total": 60.00, "order_suffix": "9c59-0d1dedc4969b"},
    {"id": 620448181, "number": "FBV 341/2026", "total": 308.95, "order_suffix": "aaa4-e763e1206a1e"},
    {"id": 620448245, "number": "FBV 342/2026", "total": 179.00, "order_suffix": "b9ca-7f92d3ec60b8"},
    {"id": 620448309, "number": "FBV 343/2026", "total": 229.00, "order_suffix": "b727-4bfd698bc7d4"},
    {"id": 620448373, "number": "FBV 344/2026", "total": 82.00, "order_suffix": "b09e-572fb364178c"},
    {"id": 620448501, "number": "FBV 345/2026", "total": 198.00, "order_suffix": "a057-8f1ad7cb1230"},
    {"id": 620448565, "number": "FBV 346/2026", "total": 198.00, "order_suffix": "a3b4-27708eea4f6f"},
    {"id": 620448757, "number": "FBV 347/2026", "total": 82.00, "order_suffix": "9c59-0d1dedc4969b"},
    {"id": 620448821, "number": "FBV 348/2026", "total": 98.00, "order_suffix": "a3b4-27708eea4f6f"},
    {"id": 620448885, "number": "FBV 349/2026", "total": 189.00, "order_suffix": "8f37-811bbbf37ca0"},
    {"id": 620448949, "number": "FBV 350/2026", "total": 198.00, "order_suffix": "92d4-a1f19a0c7034"},
    {"id": 620449077, "number": "FBV 351/2026", "total": 199.00, "order_suffix": "a42a-ed5f40aaa868"},
    {"id": 620449141, "number": "FBV 352/2026", "total": 262.00, "order_suffix": "a3b1-4316fada8457"},
    {"id": 620449205, "number": "FBV 353/2026", "total": 199.00, "order_suffix": "b9ca-7f92d3ec60b8"},
    {"id": 620456501, "number": "FBV 355/2026", "total": 179.00, "order_suffix": "8e8a-b13312e55057"},
    {"id": 620456565, "number": "FBV 356/2026", "total": 229.00, "order_suffix": "b09e-572fb364178c"},
    {"id": 620456629, "number": "FBV 357/2026", "total": 60.00, "order_suffix": "9c59-0d1dedc4969b"},
    {"id": 620456693, "number": "FBV 358/2026", "total": 308.95, "order_suffix": "aaa4-e763e1206a1e"},
    {"id": 620456821, "number": "FBV 359/2026", "total": 179.00, "order_suffix": "b9ca-7f92d3ec60b8"},
    {"id": 620456885, "number": "FBV 360/2026", "total": 229.00, "order_suffix": "b727-4bfd698bc7d4"},
    {"id": 620456949, "number": "FBV 361/2026", "total": 82.00, "order_suffix": "b09e-572fb364178c"},
    {"id": 620457077, "number": "FBV 362/2026", "total": 198.00, "order_suffix": "a057-8f1ad7cb1230"},
    {"id": 620457141, "number": "FBV 363/2026", "total": 198.00, "order_suffix": "a3b4-27708eea4f6f"},
    {"id": 620457205, "number": "FBV 364/2026", "total": 82.00, "order_suffix": "9c59-0d1dedc4969b"},
    {"id": 620457269, "number": "FBV 365/2026", "total": 98.00, "order_suffix": "a3b4-27708eea4f6f"},
    {"id": 620457333, "number": "FBV 366/2026", "total": 189.00, "order_suffix": "8f37-811bbbf37ca0"},
    {"id": 620457397, "number": "FBV 367/2026", "total": 198.00, "order_suffix": "92d4-a1f19a0c7034"},
    {"id": 620457461, "number": "FBV 368/2026", "total": 199.00, "order_suffix": "a42a-ed5f40aaa868"},
    {"id": 620457525, "number": "FBV 369/2026", "total": 262.00, "order_suffix": "a3b1-4316fada8457"},
    {"id": 620457589, "number": "FBV 370/2026", "total": 199.00, "order_suffix": "b9ca-7f92d3ec60b8"},
    {"id": 620457653, "number": "FBV 371/2026", "total": 217.00, "order_suffix": "b822-3b889f6dec5e"},
]


@dataclass
class VerifyResult:
    ok: bool
    messages: list[str]


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"corrected": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _parse_find_invoices(result: dict) -> list[dict]:
    block = result.get("invoices", {})
    out: list[dict] = []
    if isinstance(block, dict):
        for key in sorted(block):
            if key == "parameters":
                continue
            entry = block[key]
            if isinstance(entry, dict) and "invoice" in entry:
                out.append(entry["invoice"])
    return out


def _retry_wfirma(fn, *, attempts: int = 4, pause: float = 2.0):
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except WFirmaError as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            time.sleep(pause * attempt)
    assert last_exc is not None
    raise last_exc


def get_invoice_retry(client: WFirmaClient, invoice_id: int) -> dict:
    return _retry_wfirma(lambda: get_invoice(client, invoice_id))


def find_existing_correction(client: WFirmaClient, original_invoice_id: int) -> Optional[dict]:
    """Szukaj korekty po parent.id — bez dodatkowych GET na wynikach find."""
    for field in ("Invoice.parent.id", "parent"):
        data = {
            "invoices": {
                "parameters": {
                    "conditions": {
                        "and": [
                            {
                                "condition": {
                                    "field": "type",
                                    "operator": "eq",
                                    "value": "correction",
                                }
                            },
                            {
                                "condition": {
                                    "field": field,
                                    "operator": "eq",
                                    "value": str(original_invoice_id),
                                }
                            },
                        ]
                    },
                    "fields": [
                        {"field": "Invoice.id"},
                        {"field": "Invoice.fullnumber"},
                        {"field": "Invoice.total"},
                        {"field": "Invoice.parent"},
                    ],
                    "limit": 5,
                }
            }
        }
        try:
            result = _retry_wfirma(lambda d=data: client.request("invoices/find", data=d))
        except WFirmaError:
            continue
        for inv in _parse_find_invoices(result):
            parent = inv.get("parent") or {}
            if str(parent.get("id")) == str(original_invoice_id):
                return inv
    return None


def verify_original_invoice(client: WFirmaClient, entry: dict) -> VerifyResult:
    messages: list[str] = []
    inv_id = int(entry["id"])
    inv = get_invoice_retry(client, inv_id)
    number = inv.get("fullnumber", entry["number"])
    total = float(inv.get("total") or 0)
    inv_type = inv.get("type", "")
    desc = inv.get("description", "")

    messages.append(f"Oryginal: {number} id={inv_id} type={inv_type} total={total:.2f}")
    messages.append(f"  opis: {desc!r}")

    if inv_type != "bill":
        return VerifyResult(False, messages + [f"  FAIL: oczekiwano type=bill, jest {inv_type!r}"])

    expected = float(entry["total"])
    if abs(total - expected) > 0.02:
        messages.append(f"  WARN: kwota {total:.2f} != oczekiwana {expected:.2f}")

    existing = find_existing_correction(client, inv_id)
    if existing:
        messages.append(
            f"  SKIP: juz istnieje korekta {existing.get('fullnumber')} "
            f"id={existing.get('id')} total={existing.get('total')}"
        )
        return VerifyResult(False, messages)

    return VerifyResult(True, messages)


def verify_correction(
    client: WFirmaClient,
    original_id: int,
    correction: dict,
    expected_original_total: float,
) -> VerifyResult:
    messages: list[str] = []
    corr_id = int(correction["invoice_id"])
    corr = get_invoice_retry(client, corr_id)
    corr_number = corr.get("fullnumber", correction["invoice_number"])
    corr_total = float(corr.get("total") or 0)
    corr_type = corr.get("type", "")
    parent = corr.get("parent", {})
    parent_id = parent.get("id") if isinstance(parent, dict) else None

    messages.append(f"Korekta: {corr_number} id={corr_id} type={corr_type} total={corr_total:.2f}")
    messages.append(f"  parent.id={parent_id}")

    ok = True
    if corr_type != "correction":
        messages.append(f"  FAIL: type={corr_type!r}")
        ok = False
    if str(parent_id) != str(original_id):
        messages.append(f"  FAIL: parent {parent_id} != oryginal {original_id}")
        ok = False
    # Korekta zerujaca powinna miec total ujemny (anuluje calosc)
    if corr_total >= -0.01:
        messages.append(f"  FAIL: oczekiwano total < 0, jest {corr_total:.2f}")
        ok = False
    if abs(corr_total + expected_original_total) > 0.05:
        messages.append(
            f"  WARN: |korekta|={abs(corr_total):.2f} vs oryginal={expected_original_total:.2f}"
        )

    if ok:
        messages.append("  OK: korekta wyglada poprawnie")
    return VerifyResult(ok, messages)


def process_one(
    client: WFirmaClient,
    entry: dict,
    *,
    dry_run: bool,
) -> dict:
    inv_id = int(entry["id"])
    pre = verify_original_invoice(client, entry)
    for line in pre.messages:
        print(line)

    if not pre.ok:
        return {"status": "skipped", "invoice_id": inv_id, "number": entry["number"]}

    if dry_run:
        print("  DRY-RUN: pominieto wystawienie korekty")
        return {"status": "dry_run", "invoice_id": inv_id, "number": entry["number"]}

    print("  Wystawiam korekte zerujaca...")
    inv = _retry_wfirma(
        lambda: create_correction_invoice(
            client,
            original_invoice_id=inv_id,
            corrected_items=None,
            description=CORRECTION_REASON,
        )
    )
    print(
        f"  Utworzono: {inv['invoice_number']} id={inv['invoice_id']} "
        f"total={inv['total']:.2f}"
    )

    post = verify_correction(client, inv_id, inv, float(entry["total"]))
    for line in post.messages:
        print(line)

    status = "ok" if post.ok else "verify_failed"
    return {
        "status": status,
        "invoice_id": inv_id,
        "number": entry["number"],
        "correction_id": inv["invoice_id"],
        "correction_number": inv["invoice_number"],
        "correction_total": inv["total"],
        "verified": post.ok,
        "at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Korekty duplikatow incydentu 16.06.2026")
    parser.add_argument("--dry-run", action="store_true", help="Tylko weryfikacja, bez API add")
    parser.add_argument("--limit", type=int, default=0, help="Max liczba korekt (0=wszystkie)")
    parser.add_argument(
        "--invoice-id",
        type=int,
        help="Tylko wskazana faktura (wFirma id duplikatu)",
    )
    parser.add_argument(
        "--state-file",
        default=str(STATE_FILE),
        help="Plik postepu (domyslnie /app/data/incident_invoice_corrections.json)",
    )
    parser.add_argument("--delay", type=float, default=3.0, help="Opoznienie miedzy korektami (s)")
    args = parser.parse_args()

    targets = INCIDENT_DUPLICATES
    if args.invoice_id:
        targets = [t for t in targets if int(t["id"]) == args.invoice_id]
        if not targets:
            print(f"Nie znaleziono duplikatu id={args.invoice_id} na liscie incydentu")
            return 1

    state_path = Path(args.state_file)
    state = load_state(state_path)
    corrected = state.setdefault("corrected", {})

    app = create_app()
    with app.app_context():
        client = WFirmaClient.from_settings()

        done = 0
        results: list[dict] = []
        for entry in targets:
            inv_id = str(entry["id"])
            if inv_id in corrected and corrected[inv_id].get("status") == "ok":
                print(f"=== {entry['number']} id={entry['id']} — juz OK w state, skip ===")
                continue

            print(f"\n=== {entry['number']} id={entry['id']} ({entry['total']} PLN) ===")
            try:
                result = process_one(client, entry, dry_run=args.dry_run)
            except WFirmaError as exc:
                print(f"  ERROR wFirma: {exc}")
                result = {
                    "status": "error",
                    "invoice_id": int(entry["id"]),
                    "number": entry["number"],
                    "error": str(exc),
                    "at": datetime.now(timezone.utc).isoformat(),
                }

            results.append(result)
            if result.get("status") == "ok":
                corrected[inv_id] = result
                save_state(state_path, state)

            done += 1
            if args.limit and done >= args.limit:
                break

            if not args.dry_run and result.get("status") == "ok" and args.delay:
                time.sleep(args.delay)

        print("\n=== PODSUMOWANIE ===")
        ok = sum(1 for r in results if r.get("status") == "ok")
        skipped = sum(1 for r in results if r.get("status") == "skipped")
        failed = sum(1 for r in results if r.get("status") in ("error", "verify_failed"))
        dry = sum(1 for r in results if r.get("status") == "dry_run")
        print(f"Przetworzono: {len(results)} | OK: {ok} | skip: {skipped} | fail: {failed} | dry: {dry}")
        if args.limit and done >= args.limit and len(targets) > done:
            print(f"Pozostalo: {len(targets) - len(corrected)} (uruchom ponownie bez --limit)")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
