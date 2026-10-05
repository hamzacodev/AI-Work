"""Checks the budget function against the REAL Supabase, then deletes what it created.

Needs sql/002_functions.sql to have been run in the Supabase SQL editor.
Run from backend/:  uv run python scripts/check_budget.py
Optional: SUPABASE_PUBLISHABLE_KEY=... to also check that the public key cannot call it.
"""

import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from supabase import create_client

from app.core.budget import SupabaseBudgetStore
from app.core.config import get_settings
from app.core.db import SupabaseDealRepo, get_client

DAY = "2099-01-01"  # a far-future day, so today's real counter is never touched
results: list[bool] = []


def check(name: str, ok: bool) -> None:
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name)


def main() -> int:
    db = get_client()
    store = SupabaseBudgetStore(db)
    try:
        store.consume(DAY, None, 1, 1)
    except Exception as e:
        if "consume_llm_call" in str(e) or "PGRST202" in str(e):
            print("The function is not installed yet. Run backend/sql/002_functions.sql in the Supabase SQL editor, then run this again.")
            return 2
        raise
    db.table("usage_counters").delete().eq("day", DAY).execute()

    deal_id = SupabaseDealRepo(db).create_deal(
        {"item": "Budget check (safe to delete)", "max_price": 1, "currency": "USD", "must_haves": [], "address": "x", "phone": None},
        [{"name": "V", "contact": "v@budget.example.com", "channel": "email"}],
    )
    try:
        seq = [store.consume(DAY, None, 3, 100) for _ in range(5)]
        check("daily cap 3: ok, ok, ok, then daily_exhausted", seq == ["ok", "ok", "ok", "daily_exhausted", "daily_exhausted"])
        db.table("usage_counters").delete().eq("day", DAY).execute()

        seq = [store.consume(DAY, deal_id, 100, 2) for _ in range(4)]
        check("deal cap 2: ok, ok, then deal_exhausted", seq == ["ok", "ok", "deal_exhausted", "deal_exhausted"])
        used = db.table("deals").select("llm_calls").eq("id", deal_id).execute().data[0]["llm_calls"]
        check("the deal's counter is exactly 2", used == 2)
        day_count = db.table("usage_counters").select("count").eq("day", DAY).eq("kind", "llm").execute().data[0]["count"]
        check("refused calls were not counted against the day (2 used)", day_count == 2)

        db.table("usage_counters").delete().eq("day", DAY).execute()
        with ThreadPoolExecutor(20) as pool:
            out = list(pool.map(lambda _: store.consume(DAY, None, 5, 100), range(20)))
        check("20 calls at once with a cap of 5: exactly 5 are ok", out.count("ok") == 5)

        check("an unknown deal is refused", store.consume(DAY, str(uuid.uuid4()), 100, 100) == "unknown_deal")

        key = os.environ.get("SUPABASE_PUBLISHABLE_KEY")
        if key:
            public = create_client(get_settings().supabase_url, key)
            try:
                public.rpc("consume_llm_call", {"p_day": DAY, "p_deal_id": None, "p_daily_cap": 9, "p_deal_cap": 9}).execute()
                check("the PUBLIC key cannot call the function", False)
            except Exception:  # noqa: BLE001 - any refusal counts as "cannot call it"
                check("the PUBLIC key cannot call the function", True)
        else:
            print("skip  public-key check (set SUPABASE_PUBLISHABLE_KEY to run it)")
    finally:
        db.table("usage_counters").delete().eq("day", DAY).execute()
        db.table("deals").delete().eq("id", deal_id).execute()
        print("cleanup: done")
    print("ALL PASS" if all(results) else "SOME FAILED")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
