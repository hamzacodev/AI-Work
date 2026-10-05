"""Checks the Supabase connection: writes one test row, reads it, deletes it.

Run from backend/:  uv run python scripts/check_db.py
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from supabase import create_client

from app.core.config import get_settings


def main() -> int:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        print("FAIL: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is empty in backend/.env")
        return 1

    db = create_client(s.supabase_url, s.supabase_service_role_key)
    today = datetime.now(UTC).date().isoformat()
    try:
        db.table("usage_counters").upsert({"day": today, "kind": "check", "count": 1}).execute()
        rows = db.table("usage_counters").select("*").eq("kind", "check").execute().data
        db.table("usage_counters").delete().eq("kind", "check").execute()
    except Exception as e:  # noqa: BLE001 - this is a diagnostic script
        print(f"FAIL: {type(e).__name__}: {e}")
        return 1

    if rows and rows[0]["count"] == 1:
        print("OK: wrote, read and deleted a test row in usage_counters")
        return 0
    print(f"FAIL: unexpected rows: {rows}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
