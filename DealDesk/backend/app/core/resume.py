"""resume_pending(): pick up vendors whose work was interrupted (server restart, sleeping host).

It runs when the server starts and whenever someone opens a deal. It never does the agent's
work itself. It hands each vendor to a PROCESSOR, the function that runs one agent turn.
The processor does not exist yet (Phase 3), so until one is registered nothing is resumed.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from app.core.queue import Lease, VendorQueue

log = logging.getLogger("dealdesk.resume")

LEASE_SECONDS = 120.0
RESUME_BATCH = 50

Processor = Callable[[str], Awaitable[None]]  # takes a vendor id, runs one agent turn
_processor: Processor | None = None
_tasks: set[asyncio.Task] = set()


def set_processor(fn: Processor | None) -> None:
    global _processor
    _processor = fn


def get_processor() -> Processor | None:
    return _processor


def _spawn(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)  # keep a reference, or Python may delete a running task
    task.add_done_callback(_finished)


def _finished(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if not task.cancelled() and task.exception() is not None:
        log.error("vendor task failed", exc_info=task.exception())


async def wait_for_tasks() -> None:
    """Waits for running vendor tasks. Used by tests and at shutdown."""
    if _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def run_with_lease(queue: VendorQueue, lease: Lease, processor: Processor, seconds: float) -> None:
    """Runs the processor while keeping the lease alive. Releases it only if the work succeeded.

    If the work fails the lease is left to run out. That is a built-in pause before the next try,
    so a vendor that keeps crashing is not retried in a tight loop.
    """
    current = lease

    async def keep_alive() -> None:
        nonlocal current
        while True:
            await asyncio.sleep(seconds / 3)
            renewed = await asyncio.to_thread(queue.renew, current, seconds)
            if renewed is None:  # someone else holds it now. Stop renewing.
                log.warning("lease lost for vendor %s", lease.vendor_id)
                return
            current = renewed

    keeper = asyncio.create_task(keep_alive())
    try:
        await processor(lease.vendor_id)
    finally:
        keeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await keeper
    await asyncio.to_thread(queue.release, current)


async def resume_pending(
    queue: VendorQueue,
    processor: Processor | None = None,
    deal_id: str | None = None,
    limit: int = RESUME_BATCH,
    seconds: float = LEASE_SECONDS,
    spawn: Callable[[Coroutine[Any, Any, None]], None] = _spawn,
) -> list[str]:
    """Claims every vendor that needs work and starts a task for each. Returns the vendor ids it claimed."""
    processor = processor or _processor
    if processor is None:
        return []

    claimed: list[str] = []
    for vendor_id in await asyncio.to_thread(queue.list_resumable, deal_id, limit):
        lease = await asyncio.to_thread(queue.claim, vendor_id, seconds)
        if lease is None:  # another worker got it first
            continue
        claimed.append(vendor_id)
        spawn(run_with_lease(queue, lease, processor, seconds))
    return claimed
