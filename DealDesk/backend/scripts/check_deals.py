"""Runs the deal endpoints against the REAL Supabase, then deletes the test deal.

Run from backend/:  uv run python scripts/check_deals.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" and "main" are importable

from fastapi.testclient import TestClient

from app.core.db import get_client
from main import app


def main() -> int:
    client = TestClient(app)
    vendors = [{"name": f"Vendor {i}", "contact": f"vendor{i}@check.example.com"} for i in range(12)]
    body = {
        "item": "Check item (safe to delete)",
        "max_price": 123,
        "currency": "USD",
        "must_haves": ["a", "b"],
        "address": "Check address",
        "vendors": vendors,
    }
    deal_id = None
    try:
        res = client.post("/deals", json=body)
        print("POST /deals ->", res.status_code, res.json())
        if res.status_code != 201:
            return 1
        deal_id = res.json()["id"]
        ok = res.json()["accepted_vendors"] == 10 and res.json()["skipped_vendors"] == 2

        got = client.get(f"/deals/{deal_id}")
        data = got.json()
        print("GET  /deals/{id} ->", got.status_code, f"vendors={len(data.get('vendors', []))}", f"status={data.get('status')}")
        ok = ok and got.status_code == 200 and len(data["vendors"]) == 10
        ok = ok and "Check address" not in got.text  # the address must never be returned

        # Also stored in the database with the right values:
        row = get_client().table("deals").select("address,max_price").eq("id", deal_id).execute().data[0]
        ok = ok and row["address"] == "Check address" and float(row["max_price"]) == 123.0
        print("PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        if deal_id:
            get_client().table("deals").delete().eq("id", deal_id).execute()  # vendors are deleted too (cascade)
            left = get_client().table("deals").select("id").eq("id", deal_id).execute().data
            print("cleanup:", "done" if not left else "FAILED, delete deal " + deal_id)


if __name__ == "__main__":
    sys.exit(main())
