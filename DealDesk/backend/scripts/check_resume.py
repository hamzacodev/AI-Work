"""Checks the lease queue against the REAL Supabase, then deletes what it created.

Run from backend/:  uv run python scripts/check_resume.py
"""

import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.core.db import SupabaseDealRepo, get_client
from app.core.queue import SupabaseVendorQueue, iso

results: list[bool] = []


def check(name: str, ok: bool) -> None:
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name)


def main() -> int:
    db = get_client()
    queue = SupabaseVendorQueue(db)
    repo = SupabaseDealRepo(db)
    deal_id = repo.create_deal(
        {"item": "Lease check (safe to delete)", "max_price": 1, "currency": "USD", "must_haves": [], "address": "x", "phone": None},
        [{"name": f"V{i}", "contact": f"v{i}@lease.example.com", "channel": "email"} for i in range(3)],
    )
    try:
        ids = [v["id"] for v in repo.get_deal(deal_id)["vendors"]]
        check("3 new vendors are waiting for work", sorted(queue.list_resumable(deal_id, 50)) == sorted(ids))

        lease = queue.claim(ids[0], 60)
        check("a free vendor can be borrowed", lease is not None)
        check("a borrowed vendor cannot be borrowed again", queue.claim(ids[0], 60) is None)
        check("a borrowed vendor is not listed as waiting", ids[0] not in queue.list_resumable(deal_id, 50))

        renewed = queue.renew(lease, 60)
        check("the holder can renew", renewed is not None and renewed.until > lease.until)
        check("the old ticket can no longer renew", queue.renew(lease, 60) is None)

        db.table("vendors").update({"lease_until": iso(datetime.now(UTC) - timedelta(seconds=5))}).eq("id", ids[0]).execute()
        again = queue.claim(ids[0], 60)
        check("an expired loan can be borrowed again", again is not None)
        check("the previous holder lost the vendor", queue.renew(renewed, 60) is None)

        queue.release(again)
        check("after release the vendor is waiting again", ids[0] in queue.list_resumable(deal_id, 50))

        with ThreadPoolExecutor(8) as pool:
            wins = list(pool.map(lambda _: queue.claim(ids[1], 60), range(8)))
        check("8 workers racing for one vendor: exactly one wins", sum(w is not None for w in wins) == 1)

        db.table("vendors").update({"status": "needs_you", "lease_until": None}).eq("id", ids[2]).execute()
        check("a vendor waiting for the user is not resumed", ids[2] not in queue.list_resumable(deal_id, 50))
    finally:
        db.table("deals").delete().eq("id", deal_id).execute()
        left = db.table("deals").select("id").eq("id", deal_id).execute().data
        print("cleanup:", "done" if not left else f"FAILED, delete deal {deal_id}")
    print("ALL PASS" if all(results) else "SOME FAILED")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
