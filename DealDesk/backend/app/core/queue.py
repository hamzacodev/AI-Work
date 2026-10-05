"""Which vendors still need work, and a lease so only one worker handles a vendor at a time.

The problem: the free host sleeps and restarts, and a background task dies with the server.
A vendor in the middle of a negotiation must not be forgotten, and must not be worked on by two
tasks at once (that would send two replies).

The answer is a LEASE, like borrowing a library book for a few minutes:
  - to work on a vendor you must borrow it (claim). If someone else holds it, you cannot.
  - while you work you keep renewing the loan.
  - if you crash, nobody renews it. The loan simply runs out, and the vendor can be borrowed again.

The claim is ONE database update with the conditions inside it ("only if free or expired"),
so two workers asking at the same moment cannot both win.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

NEEDS_WORK = ("sent", "negotiating")  # statuses that still need a worker (CLAUDE.md section 8.1)


@dataclass(frozen=True)
class Lease:
    vendor_id: str
    until: str  # ISO time. It also works as the ticket: only the holder of the newest one can renew.


class VendorQueue(Protocol):
    def list_resumable(self, deal_id: str | None, limit: int) -> list[str]: ...

    def claim(self, vendor_id: str, seconds: float) -> Lease | None: ...

    def renew(self, lease: Lease, seconds: float) -> Lease | None: ...

    def release(self, lease: Lease) -> None: ...


def iso(dt: datetime) -> str:
    """Z instead of +00:00, because a plus sign inside a web address is read as a space."""
    return dt.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


class SupabaseVendorQueue:
    def __init__(self, client, now=lambda: datetime.now(UTC)) -> None:
        self.db = client
        self.now = now

    def _free(self, now: datetime) -> str:
        return f"lease_until.is.null,lease_until.lt.{iso(now)}"

    def list_resumable(self, deal_id: str | None, limit: int) -> list[str]:
        q = (
            self.db.table("vendors")
            .select("id")
            .in_("status", list(NEEDS_WORK))
            .or_(self._free(self.now()))
            .order("updated_at")
            .limit(limit)
        )
        if deal_id:
            q = q.eq("deal_id", deal_id)
        return [r["id"] for r in q.execute().data]

    def claim(self, vendor_id: str, seconds: float) -> Lease | None:
        now = self.now()
        until = iso(now + timedelta(seconds=seconds))
        rows = (
            self.db.table("vendors")
            .update({"lease_until": until, "updated_at": iso(now)})
            .eq("id", vendor_id)
            .in_("status", list(NEEDS_WORK))
            .or_(self._free(now))
            .execute()
            .data
        )
        return Lease(vendor_id, until) if rows else None

    def renew(self, lease: Lease, seconds: float) -> Lease | None:
        now = self.now()
        until = iso(now + timedelta(seconds=seconds))
        rows = (
            self.db.table("vendors")
            .update({"lease_until": until, "updated_at": iso(now)})
            .eq("id", lease.vendor_id)
            .eq("lease_until", lease.until)  # only the current holder can renew
            .execute()
            .data
        )
        return Lease(lease.vendor_id, until) if rows else None

    def release(self, lease: Lease) -> None:
        self.db.table("vendors").update({"lease_until": None, "updated_at": iso(self.now())}).eq(
            "id", lease.vendor_id
        ).eq("lease_until", lease.until).execute()


class LazySupabaseQueue:
    """Builds the database client on first use, so importing the app never needs a database."""

    def __init__(self) -> None:
        self._queue: SupabaseVendorQueue | None = None

    def _q(self) -> SupabaseVendorQueue:
        if self._queue is None:
            from app.core.db import get_client

            self._queue = SupabaseVendorQueue(get_client())
        return self._queue

    def list_resumable(self, deal_id: str | None, limit: int) -> list[str]:
        return self._q().list_resumable(deal_id, limit)

    def claim(self, vendor_id: str, seconds: float) -> Lease | None:
        return self._q().claim(vendor_id, seconds)

    def renew(self, lease: Lease, seconds: float) -> Lease | None:
        return self._q().renew(lease, seconds)

    def release(self, lease: Lease) -> None:
        self._q().release(lease)


def get_queue() -> VendorQueue:
    """FastAPI calls this to get the queue. Tests replace it with a fake."""
    return LazySupabaseQueue()
