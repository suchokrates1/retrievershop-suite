#!/usr/bin/env python3
"""Cancel duplicate Allegro shipments from 2026-06-16 incident."""
from __future__ import annotations

import sys
import time

from magazyn.allegro_api.shipment_management import (
    cancel_shipment,
    get_cancel_command_status,
    get_shipment_details,
)
from magazyn.factory import create_app

# Duplicate shipments created during reprocessing (~22:03-22:17).
# Each tuple: (shipment_id, waybill, order_id, keep_waybill)
DUPLICATES = [
    ("8ad7c0dc-0951-447e-bfa5-712f36773c14", "A004TIAF94", "allegro_b94d1a60-69ae-11f1-b822-3b889f6dec5e", "A004TIBRF9"),
    ("dd8ffd4b-8fca-4270-9a6a-839a185ad5dd", "AD02LQ90M4", "allegro_d259ffa0-6454-11f1-b09e-572fb364178c", "ca13f3d7"),
    ("5eb7af82-6045-44af-9f99-8f1e7a19dab5", "A004TIBLT3", "allegro_bf1de1b0-6641-11f1-b9ca-7f92d3ec60b8", "A004R7JTJ8"),
    ("fa344cf1-d629-48cf-a1bf-382989ce0c1c", "A004TIBO76", "allegro_0607cce1-6821-11f1-a3b4-27708eea4f6f", "A004RIQ9Z1"),
    ("8bd7a83b-1a88-496c-acd1-cd4a31becd8a", "A004TIBON0", "allegro_8f2a7160-6828-11f1-8f37-811bbbf37ca0", "A004RJ2587"),
    ("a1abd585-dfdd-43a0-b730-db4416752a80", "AD02LQ95T8", "allegro_dfa0e3e0-687d-11f1-a3b1-4316fada8457", "AD02L4V474"),
    ("e919f720-4179-4b09-862b-f925d0328d01", "A004TIBQT2", "allegro_6d830610-68a2-11f1-b9ca-7f92d3ec60b8", "A004RYKJ66"),
    # InPost numeric duplicates from same incident window
    ("aa42fbe1-b742-4c26-bedf-bf9400026c48", "620999683340035670504458", "allegro_4be30940-6444-11f1-8e8a-b13312e55057", "88256837"),
    ("51db67fd-8d9f-4765-8428-e024a80fb8e5", "620999683343460679165424", "allegro_9f6c6bf0-65a8-11f1-9c59-0d1dedc4969b", "deb173f2"),
    ("611338eb-8027-4f9b-9f3a-1c25ed6615f7", "620999683345355677522214", "allegro_069eb011-663c-11f1-aaa4-e763e1206a1e", "245020b9"),
    ("782f5ca6-acf6-4227-b3bb-cad98c94d020", "620999683370833673809935", "allegro_ec8a7641-675e-11f1-a3b4-27708eea4f6f", "17359541"),
    ("8f9e22ce-9fd8-4ea0-9140-5e71dfa7e194", "620999683302994676791559", "allegro_6dd51200-67c3-11f1-b727-4bfd698bc7d4", "4cbc81b4"),
    ("27b2704e-3f91-4a61-95c7-1143b9b6609e", "620999683397330674965838", "allegro_526fffd0-67d6-11f1-b09e-572fb364178c", "895d45d3"),
    ("a2fca1fa-8b12-47cc-a9af-cf2f7ee76ca5", "620999683322310673079280", "allegro_db9b0d20-67fb-11f1-a057-8f1ad7cb1230", "1335884f"),
    ("ab9f819f-5ff3-4f95-9d2b-d49ed7a1daf8", "620999683341219673606534", "allegro_1002a0e0-680c-11f1-9c59-0d1dedc4969b", "07054974"),
    ("5b0fb1b1-870d-4bbc-8a40-04c018b2e972", "620999683332626670401230", "allegro_f2956c30-682a-11f1-a42a-ed5f40aaa868", "7010fb4d"),
    ("658f1a9e-ceab-4827-8a04-595b94ee2132", "620999683332095679102754", "allegro_543c0900-68a1-11f1-92d4-a1f19a0c7034", "c1381275"),
]


def wait_cancel(command_id: str, timeout: float = 30.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = get_cancel_command_status(command_id).get("status", "")
        if status in ("SUCCESS", "ERROR"):
            return status
        time.sleep(1.5)
    return "TIMEOUT"


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    app = create_app()
    ok = 0
    skip = 0
    fail = 0

    with app.app_context():
        for shipment_id, waybill, order_id, keep_ref in DUPLICATES:
            try:
                details = get_shipment_details(shipment_id)
                status = details.get("status", "?")
                wb = details.get("waybill", {}).get("waybill") or waybill
                print(f"CHECK {waybill} ({shipment_id}) order={order_id[-8:]} status={status} api_waybill={wb}")
                if status == "CANCELLED":
                    print(f"  SKIP already cancelled")
                    skip += 1
                    continue
                if dry_run:
                    print(f"  DRY-RUN would cancel (keep {keep_ref})")
                    continue
                result = cancel_shipment(shipment_id)
                command_id = result.get("commandId", "")
                final = wait_cancel(command_id) if command_id else "NO_COMMAND"
                print(f"  CANCEL command={command_id} result={final}")
                if final == "SUCCESS":
                    ok += 1
                else:
                    fail += 1
            except Exception as exc:
                print(f"  FAIL {waybill}: {exc}")
                fail += 1

    print(f"\nSUMMARY ok={ok} skip={skip} fail={fail} dry_run={dry_run}")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
