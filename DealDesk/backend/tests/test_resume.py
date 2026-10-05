import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.core import resume
from app.core.queue import NEEDS_WORK, Lease, iso
from app.core.resume import (
    resume_pending,
    run_with_lease,
    set_processor,
    wait_for_tasks,
)


@dataclass
class V:
    deal_id: str
    status: str
    lease_until: datetime | None = None
    order: int = 0


class MemoryQueue:
    """The same rules as the database queue, kept in memory, with a clock we control."""

    def __init__(self):
        self.now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
        self.vendors: dict[str, V] = {}

    def add(self, vid, deal="d1", status="sent", lease_until=None):
        self.vendors[vid] = V(deal, status, lease_until, len(self.vendors))

    def _free(self, v):
        return v.lease_until is None or v.lease_until < self.now

    def list_resumable(self, deal_id, limit):
        rows = [
            (v.order, k)
            for k, v in self.vendors.items()
            if v.status in NEEDS_WORK and self._free(v) and (deal_id is None or v.deal_id == deal_id)
        ]
        return [k for _, k in sorted(rows)][:limit]

    def claim(self, vendor_id, seconds):
        v = self.vendors[vendor_id]
        if v.status not in NEEDS_WORK or not self._free(v):
            return None
        v.lease_until = self.now + timedelta(seconds=seconds)
        return Lease(vendor_id, iso(v.lease_until))

    def renew(self, lease, seconds):
        v = self.vendors[lease.vendor_id]
        if v.lease_until is None or iso(v.lease_until) != lease.until:
            return None
        v.lease_until = self.now + timedelta(seconds=seconds)
        return Lease(lease.vendor_id, iso(v.lease_until))

    def release(self, lease):
        v = self.vendors[lease.vendor_id]
        if v.lease_until is not None and iso(v.lease_until) == lease.until:
            v.lease_until = None


@pytest.fixture(autouse=True)
def clean():
    set_processor(None)
    yield
    set_processor(None)


class Recorder:
    def __init__(self, fail_on=(), delay=0.0):
        self.seen: list[str] = []
        self.fail_on = set(fail_on)
        self.delay = delay

    async def __call__(self, vendor_id):
        self.seen.append(vendor_id)
        if self.delay:
            await asyncio.sleep(self.delay)
        if vendor_id in self.fail_on:
            raise RuntimeError("boom")


# ---------------------------------------------------------------- the queue rules


def test_only_sent_and_negotiating_vendors_with_a_free_lease_are_listed():
    q = MemoryQueue()
    q.add("sent", status="sent")
    q.add("neg", status="negotiating")
    q.add("needs", status="needs_you")
    q.add("closed", status="closed")
    q.add("blocked", status="blocked")
    q.add("replied", status="replied")
    q.add("leased", status="sent", lease_until=q.now + timedelta(seconds=30))
    q.add("expired", status="sent", lease_until=q.now - timedelta(seconds=1))
    assert q.list_resumable(None, 50) == ["sent", "neg", "expired"]


def test_a_vendor_can_be_borrowed_only_once_at_a_time():
    q = MemoryQueue()
    q.add("v")
    first = q.claim("v", 120)
    assert first is not None
    assert q.claim("v", 120) is None


def test_an_expired_loan_can_be_borrowed_again():
    q = MemoryQueue()
    q.add("v")
    q.claim("v", 120)
    q.now += timedelta(seconds=121)
    assert q.claim("v", 120) is not None


def test_only_the_current_holder_can_renew():
    q = MemoryQueue()
    q.add("v")
    old = q.claim("v", 10)
    q.now += timedelta(seconds=11)
    new = q.claim("v", 10)  # someone else took over after the loan ran out
    assert q.renew(old, 10) is None
    assert q.renew(new, 10) is not None


def test_release_frees_the_vendor_but_an_old_ticket_cannot_release_it():
    q = MemoryQueue()
    q.add("v")
    old = q.claim("v", 10)
    q.now += timedelta(seconds=11)
    new = q.claim("v", 10)
    q.release(old)  # stale ticket, does nothing
    assert q.claim("v", 10) is None
    q.release(new)
    assert q.claim("v", 10) is not None


# ---------------------------------------------------------------- resume_pending


async def test_without_a_registered_processor_nothing_happens():
    q = MemoryQueue()
    q.add("v")
    assert await resume_pending(q) == []
    assert q.vendors["v"].lease_until is None  # nothing was borrowed


async def test_every_waiting_vendor_is_handed_to_the_processor():
    q = MemoryQueue()
    for v in ("a", "b", "c"):
        q.add(v)
    rec = Recorder()
    claimed = await resume_pending(q, rec)
    await wait_for_tasks()
    assert claimed == ["a", "b", "c"] and sorted(rec.seen) == ["a", "b", "c"]


async def test_the_registered_processor_is_used():
    q = MemoryQueue()
    q.add("v")
    rec = Recorder()
    set_processor(rec)
    await resume_pending(q)
    await wait_for_tasks()
    assert rec.seen == ["v"]


async def test_calling_twice_at_once_does_not_run_a_vendor_twice():
    q = MemoryQueue()
    q.add("v")
    rec = Recorder(delay=0.05)
    first = await resume_pending(q, rec)
    second = await resume_pending(q, rec)  # the first task is still running and holds the lease
    await wait_for_tasks()
    assert first == ["v"] and second == [] and rec.seen == ["v"]


async def test_overlapping_resumes_never_double_run_a_vendor():
    q = MemoryQueue()
    for i in range(10):
        q.add(f"v{i}")
    rec = Recorder(delay=0.02)
    await asyncio.gather(*[resume_pending(q, rec) for _ in range(5)])
    await wait_for_tasks()
    assert sorted(rec.seen) == sorted(f"v{i}" for i in range(10))  # each exactly once


async def test_a_vendor_whose_lease_ran_out_is_picked_up_again():
    q = MemoryQueue()
    q.add("v", lease_until=q.now - timedelta(seconds=5))  # a worker died holding it
    rec = Recorder()
    await resume_pending(q, rec)
    await wait_for_tasks()
    assert rec.seen == ["v"]


async def test_only_the_asked_deal_is_resumed():
    q = MemoryQueue()
    q.add("a", deal="d1")
    q.add("b", deal="d2")
    rec = Recorder()
    await resume_pending(q, rec, deal_id="d2")
    await wait_for_tasks()
    assert rec.seen == ["b"]


async def test_the_batch_size_is_respected():
    q = MemoryQueue()
    for i in range(10):
        q.add(f"v{i}")
    rec = Recorder()
    assert len(await resume_pending(q, rec, limit=4)) == 4
    await wait_for_tasks()


async def test_the_lease_is_released_when_the_work_succeeds():
    q = MemoryQueue()
    q.add("v")
    await resume_pending(q, Recorder())
    await wait_for_tasks()
    assert q.vendors["v"].lease_until is None


async def test_a_crashing_vendor_keeps_its_lease_so_it_is_not_retried_in_a_loop(caplog):
    q = MemoryQueue()
    q.add("bad")
    q.add("good")
    rec = Recorder(fail_on={"bad"})
    await resume_pending(q, rec)
    await wait_for_tasks()
    assert q.vendors["good"].lease_until is None  # finished normally
    assert q.vendors["bad"].lease_until is not None  # left to run out
    assert "bad" not in await resume_pending(q, rec)  # the crashing vendor is not picked up again straight away
    assert "vendor task failed" in caplog.text  # and the failure was logged, not hidden


# ---------------------------------------------------------------- keeping the lease alive


async def test_a_long_job_keeps_renewing_its_lease():
    q = MemoryQueue()
    q.add("v")
    lease = q.claim("v", 0.3)
    q.now = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
    seen_during = {}

    async def slow(vendor_id):
        for _ in range(7):
            await asyncio.sleep(0.1)
            q.now += timedelta(seconds=0.1)  # time passes in the queue's own clock
        seen_during["claim"] = q.claim("v", 0.3)  # an impatient second worker tries to take it

    await run_with_lease(q, lease, slow, seconds=0.3)
    assert seen_during["claim"] is None  # the lease was still alive after 0.7s of work (it was only 0.3s long)
    assert q.vendors["v"].lease_until is None  # and released at the end


async def test_keep_alive_stops_quietly_if_the_lease_was_lost():
    q = MemoryQueue()
    q.add("v")
    lease = q.claim("v", 0.3)
    q.vendors["v"].lease_until = q.now + timedelta(seconds=999)  # someone else changed it

    async def work(vendor_id):
        await asyncio.sleep(0.2)

    await run_with_lease(q, lease, work, seconds=0.3)  # must not raise


def test_task_registry_starts_empty():
    assert resume._tasks == set()
