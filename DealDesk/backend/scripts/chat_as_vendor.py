"""Chat in the terminal where YOU play a vendor and the DealDesk agent is the buyer.

Run from backend/:
    uv run python scripts/chat_as_vendor.py                 # the real model (Ollama). Each step can take 10 to 60 seconds.
    uv run python scripts/chat_as_vendor.py --no-model      # a quick rehearsal with a scripted writer, no Ollama needed
Options: --you Alpha  --verbose (show every step)  --real-research (use Tavily credits, default is a fixed market price)

The buyer wants a Dell XPS 15 and will pay up to 800 (a secret). The market is 640 to 790 around 700.
Two fake vendors, Beta (friendly) and Gamma (pushy), reply on their own. Type your replies as the vendor.
Commands: /summary  /events  /quit
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so "app" is importable

from app.agents.manager import DealManager, ManagerDeps
from app.negotiation.tactics import Tactics
from app.schemas.records import DealRecord, InMemoryDealStore, Outbound, VendorRecord
from app.simulator.scripted_llm import ScriptedLLM, fixed_research
from app.simulator.vendor_sim import VendorSim

DEAL_ID = "terminal"
MEDIAN = 700.0


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--you", default="Alpha")
    ap.add_argument("--no-model", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--real-research", action="store_true")
    args = ap.parse_args()

    if args.no_model:
        llm = ScriptedLLM()
    else:
        from app.core.config import get_settings
        from app.core.llm import LLM

        llm = LLM(get_settings())  # no database budget counter here: this is a local test with a fake deal id
    research_fn = fixed_research
    if args.real_research:
        raise SystemExit("--real-research is wired in Phase 4 (it needs the Supabase cache and credit counter). Use the fixed market price for now.")

    names = [args.you, *[n for n in ("Alpha", "Beta", "Gamma") if n != args.you][:2]]
    personas = {names[1]: "friendly", names[2]: "pushy"}
    store = InMemoryDealStore()
    deal = DealRecord(
        id=DEAL_ID, item="Dell XPS 15", max_price=800.0, must_haves=["16GB RAM"], address="12 Example Street, Karachi",
        tactics=Tactics(may_buy_quantity=2, can_decide_today=True), max_rounds=4,
    )  # fmt: skip
    for n in names:
        deal.vendors[n.lower()] = VendorRecord(n.lower(), n, f"{n.lower()}@shop.example.com")
    store.add(deal)
    sims = {n.lower(): VendorSim(p, MEDIAN, "Dell XPS 15", seed=i) for i, (n, p) in enumerate(personas.items())}
    background: set[asyncio.Task] = set()
    you = args.you.lower()

    def show(name: str, who: str, text: str) -> None:
        print(f"  [{name}] {who}: {text}")

    async def sim_reply(vendor_id: str, out: Outbound) -> None:
        sim = sims[vendor_id]
        turn = await sim.opening() if out.action == "first_message" else await sim.reply(out.counter_price)
        show(deal.vendors[vendor_id].name, "vendor", turn.text)
        await mgr.on_vendor_message(DEAL_ID, vendor_id, turn.text)

    async def on_send(out: Outbound) -> None:
        name = deal.vendors[out.vendor_id].name
        if out.vendor_id == you:
            print(f"\nAGENT -> {name}: {out.text}")
        else:
            show(name, "agent", out.text)
            task = asyncio.create_task(sim_reply(out.vendor_id, out))  # not awaited here: the turn lock is still held
            background.add(task)
            task.add_done_callback(background.discard)

    mgr = DealManager(ManagerDeps(llm=llm, store=store, research=research_fn, on_send=on_send))  # type: ignore[arg-type]

    async def settle() -> None:
        while background:
            await asyncio.gather(*list(background), return_exceptions=False)

    async def print_summary() -> None:
        s = await mgr.summary(DEAL_ID)
        print("\n" + "=" * 70 + f"\n{s.headline}")
        for r in s.ranking:
            flags = f"{'firm, ' if r.firm else ''}{r.status}{', ' + r.stop_reason if r.stop_reason else ''}"
            print(f"  {r.name:6} ${r.price:g}  ({flags}){'  WARNING: ' + r.warning if r.warning else ''}")
        print("=" * 70)

    print(__doc__.split("Run from")[0].strip())
    print(f"\nYou are {args.you}. The agent writes first. Type your replies. /summary /events /quit\n")
    await mgr.start(DEAL_ID)
    await settle()

    while True:
        v = deal.vendors[you]
        if v.status != "negotiating":
            why = {"firm_price": "you said the price is final", "round_limit": "the rounds are used", "good_price": "your price is good"}.get(v.stop_reason or "", v.stop_reason or "")
            print(f"  (The agent has stopped texting you: {why or v.status}. The chat stays open. You can still write.)")
        try:
            text = (await asyncio.to_thread(input, f"You ({args.you}) > ")).strip()
        except EOFError:
            text = "/quit"
        if text == "/quit":
            break
        if text == "/summary":
            await print_summary()
            continue
        if text == "/events":
            for e in v.events[-12:]:
                print(f"  - {e.agent}: {e.text}")
            continue
        if not text:
            continue
        before = len(v.events)
        state = await mgr.on_vendor_message(DEAL_ID, you, text)
        await settle()
        if args.verbose:
            for e in v.events[before:]:
                print(f"  . {e.agent}: {e.text}")
        if state.get("outcome") == "blocked":
            print(f"  (BLOCKED by the Safety Guard: {next((e.text for e in reversed(v.events) if e.agent == 'Safety Guard'), '')})")
        await print_summary()
    await print_summary()


asyncio.run(main())
