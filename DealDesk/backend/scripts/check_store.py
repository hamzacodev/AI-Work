"""Proves the agent's memory works in the REAL Supabase database (no model, no network except Supabase).

Run from backend/ AFTER running sql/004_agent_state.sql in the Supabase SQL editor:
    uv run python scripts/check_store.py
It creates a test deal, runs a short negotiation with a scripted writer, then creates a BRAND NEW store (like a
server restart), reloads the deal, checks nothing was lost, and deletes the test deal.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" and "tests" are importable

from app.agents.manager import DealManager, ManagerDeps
from app.core.db import SupabaseDealRepo, SupabaseDealStore, get_client
from tests.test_manager import FakeLLM, research


async def main() -> None:
    client = get_client()
    repo = SupabaseDealRepo(client)
    deal_id = repo.create_deal(
        {"item": "Dell XPS 15", "max_price": 800, "currency": "USD", "must_haves": ["16GB RAM"], "address": "12 Example Street", "status": "created"},
        [
            {"name": "Alpha", "contact": "alpha@shop.example.com", "channel": "email", "status": "negotiating"},
            {"name": "Beta", "contact": "beta@shop.example.com", "channel": "email", "status": "negotiating"},
        ],
    )
    try:
        mgr = DealManager(ManagerDeps(llm=FakeLLM(), store=SupabaseDealStore(client), research=research()))  # type: ignore[arg-type]
        deal = await mgr.deps.store.get(deal_id)
        alpha, beta = list(deal.vendors)
        await mgr.start(deal_id)
        await mgr.on_vendor_message(deal_id, alpha, "$880, ready to ship")
        await mgr.on_vendor_message(deal_id, beta, "$640 and that is good.")
        print("Run 1 done. Now simulating a server restart with a brand new store...")

        again = await SupabaseDealStore(client).get(deal_id)
        a, b = again.vendors[alpha], again.vendors[beta]
        print(f"Alpha: offer={a.offer} last_counter={a.last_counter} rounds={a.rounds} status={a.status} messages={len(a.conversation)} events={len(a.events)}")
        print(f"Beta:  offer={b.offer} status={b.status} stop_reason={b.stop_reason} messages={len(b.conversation)}")
        print(f"Research saved: {again.research is not None and again.research.median}")
        assert a.offer == 880 and a.last_counter == 651 and len(a.conversation) == 3, "Alpha was not saved correctly"
        assert b.offer == 640 and again.research is not None, "Beta or the research was not saved"
        print("OK: everything the agent knew came back from the database.")
    finally:
        client.table("deals").delete().eq("id", deal_id).execute()  # vendors, messages and events go with it (cascade)
        print("Test deal deleted.")


asyncio.run(main())
