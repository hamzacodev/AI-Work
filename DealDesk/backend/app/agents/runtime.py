"""The Runtime: the glue between the web API and the agent.

In easy words: the API receives "start this deal" or "the vendor wrote this". The Runtime hands that to the Manager
in the background (a negotiation takes minutes, and the website polls for progress), plays the FAKE vendors in
simulator mode, and picks up unfinished work after a restart.

  start_deal       : send the first message to every vendor
  human_message    : a person typed as the vendor ("take control"). The Manager answers as the buyer.
  set_played_by    : switch one vendor between the simulator and a person
  resume_vendor    : the processor for core/resume.py. After a restart it finishes whatever a vendor was waiting for.

Fake vendors (simulator): after every buyer message a VendorSim answers, with prices decided by code and every
message marked `simulated`. A person playing a vendor is never answered by the simulator.
"""

import asyncio
import copy
import logging
import zlib
from collections.abc import Awaitable, Callable

from app.agents import closer
from app.agents.fact_rules import Turn
from app.agents.manager import DealManager, ManagerDeps, TurnState
from app.core.config import get_settings
from app.core.resume import _spawn
from app.schemas.records import (
    DealRecord,
    DealStore,
    InMemoryDealStore,
    Outbound,
    PlayedBy,
    VendorRecord,
)
from app.simulator.vendor_sim import VendorSim, reply_delay

log = logging.getLogger("dealdesk.runtime")

PERSONA_CYCLE = ("friendly", "pushy", "stubborn", "liar")  # the attacker is only used by "Try to trick it"


def persona_for(index: int) -> str:
    return PERSONA_CYCLE[index % len(PERSONA_CYCLE)]


class NotYours(Exception):
    """The vendor is played by the simulator, so a person cannot type for it."""


# The WhatsApp demonstration scenarios: the item and a fixed maximum price (the demo market price is derived from it, no web search).
DEMO_SCENARIOS: dict[str, tuple[str, float]] = {
    "xps": ("Dell XPS 15", 800.0),
    "iphone": ("iPhone 15 128GB", 750.0),
    "sony": ("Sony WH-1000XM5", 350.0),
}


class _DailyBudgetOnly:
    """Wraps the model for the demonstration chat. The demo deal is not in the database, so its calls count against the DAILY budget
    only (no deal id), instead of failing the per-deal budget check."""

    def __init__(self, model) -> None:
        self._inner = model  # only forwards: the real call (and its label) is made by the agent that uses this wrapper

    async def complete_json(self, role, system, user, schema, deal_id=None):
        return await self._inner.complete_json(role, system, user, schema, None)

    async def complete(self, role, system, user, deal_id=None):
        return await self._inner.complete(role, system, user, None)


class Runtime:
    def __init__(
        self,
        store: DealStore,
        find_deal: Callable[[str], Awaitable[str | None]] | None = None,
        delay: Callable[[], float] | None = None,
        spawn: Callable = _spawn,
    ) -> None:
        self.store = store
        self.find_deal = find_deal  # vendor id -> deal id (the lease queue only knows vendor ids)
        self.delay = delay or (lambda: 0.0)
        self._spawn = spawn
        self._sims: dict[str, VendorSim] = {}
        self.manager: DealManager | None = None  # set by attach()

    def attach(self, manager: DealManager) -> None:
        self.manager = manager

    # ------------------------------------------------------------ the fake vendors

    def _sim_for(self, deal: DealRecord, v: VendorRecord) -> VendorSim:
        if v.vendor_id not in self._sims:
            median = deal.research.median if deal.research is not None and deal.research.available and deal.research.median else deal.max_price * 0.875
            sim = VendorSim(v.persona or "friendly", median, deal.item, deal.currency, seed=zlib.crc32(v.vendor_id.encode()))
            if v.offer is not None:  # after a restart the fake vendor carries on from the last price it said
                sim.current = v.offer
                sim.rounds = v.rounds
            self._sims[v.vendor_id] = sim
        return self._sims[v.vendor_id]

    async def on_send(self, out: Outbound) -> None:
        """The Manager sent a message. If a fake vendor plays this vendor, it answers (later, in the background)."""
        deal = await self.store.get(out.deal_id)
        v = deal.vendors[out.vendor_id]
        # A chat reply or a goodbye has no price: the fake vendor does not answer it (no endless small talk).
        if v.played_by == "simulator" and out.action not in ("chat", "close"):
            self._spawn(self._sim_reply(out))

    async def _sim_reply(self, out: Outbound) -> None:
        assert self.manager is not None
        await asyncio.sleep(self.delay())
        deal = await self.store.get(out.deal_id)
        v = deal.vendors[out.vendor_id]
        if v.played_by != "simulator" or v.status == "blocked":
            return
        if not v.conversation or v.conversation[-1].sender == "vendor":
            return  # the fake vendor already answered the last message (a recovery and the normal reply must not both answer)
        sim = self._sim_for(deal, v)
        turn = await sim.opening() if out.action == "first_message" else await sim.reply(out.counter_price)
        await self.manager.on_vendor_message(out.deal_id, out.vendor_id, turn.text, simulated=True)

    # ------------------------------------------------------------ what the API calls

    async def start_deal(self, deal_id: str) -> None:
        assert self.manager is not None
        await self.manager.start(deal_id)

    async def human_message(self, deal_id: str, vendor_id: str, text: str) -> TurnState:
        assert self.manager is not None
        deal = await self.store.get(deal_id)
        if deal.vendors[vendor_id].played_by != "you":
            raise NotYours("Switch this vendor to 'You' before typing as the vendor.")
        return await self.manager.on_vendor_message(deal_id, vendor_id, text)

    async def set_played_by(self, deal_id: str, vendor_id: str, who: PlayedBy) -> None:
        deal = await self.store.get(deal_id)
        v = deal.vendors[vendor_id]
        v.played_by = who
        await self.store.save(deal)
        if who == "simulator" and v.conversation and v.conversation[-1].sender == "agent" and v.status != "blocked":
            # the fake vendor takes over a chat that is waiting for the vendor's answer
            self._spawn(self._sim_reply(Outbound(deal_id, vendor_id, v.conversation[-1].text, "counter", v.last_counter)))

    # ------------------------------------------------------------ the user's decisions (the Closer)

    async def decide(self, deal_id: str, vendor_id: str, action: str, counter_price: float | None = None, confirm_over_limit: bool = False) -> None:
        """Accept, counter or reject. Raises closer.DecisionError or closer.NeedsConfirmation when it cannot go ahead."""
        if action == "accept":
            await closer.accept(self.store, deal_id, vendor_id, confirm_over_limit)
        elif action == "reject":
            await closer.reject(self.store, deal_id, vendor_id)
        else:
            out = await closer.counter(self.store, deal_id, vendor_id, counter_price, confirm_over_limit)
            deal = await self.store.get(deal_id)
            if deal.vendors[vendor_id].played_by == "simulator":  # a fake vendor answers the user's counter
                self._spawn(self._sim_reply(out))

    async def finish(self, deal_id: str, action: str) -> None:
        await closer.finish(self.store, deal_id, action)

    async def trick(self, deal_id: str, vendor_id: str, message: str) -> dict:
        """"Try to trick it": run a message through the REAL pipeline on a throwaway COPY of the deal.
        You see what the agent would do (blocked or not, and what it would reply). Nothing real changes: the copy is thrown away."""
        assert self.manager is not None
        deal = await self.store.get(deal_id)
        if vendor_id not in deal.vendors:
            raise KeyError(vendor_id)
        return await self._dry_run(copy.deepcopy(deal), vendor_id, message)

    async def demo_chat(
        self, scenario: str, history: list[tuple[str, str]], message: str,
        custom: tuple[str, float, str, list[str]] | None = None,
    ) -> dict:  # fmt: skip
        """The WhatsApp demonstration: you play the vendor, the REAL agent answers. It runs on a throwaway deal built here (fixed demo
        market price, so no search credits), so nothing in the database is read or written. Same result shape as `trick`."""
        from app.guardrails.prices import extract_prices, numbers_in
        from app.simulator.scripted_llm import fixed_research

        # `custom` is the buyer's own request from the page: (item, maximum, currency, must-haves). The text is untrusted like any other.
        item, max_price, currency, must_haves = custom if custom else (*DEMO_SCENARIOS[scenario], "USD", [])
        deal = DealRecord(id="demo", item=item, max_price=max_price, currency=currency, must_haves=must_haves, address="12 Example Street, Karachi", max_rounds=get_settings().max_rounds)
        deal.research = await fixed_research(deal)
        known = numbers_in(item)
        v = VendorRecord("demo-v1", "Demo vendor", "demo@vendor.example.com", played_by="you")
        for sender, text in history:
            v.conversation.append(Turn(sender="vendor" if sender == "vendor" else "agent", text=text))
            prices = extract_prices(text, known)
            if sender == "vendor" and prices:
                v.offers_so_far.append(prices[0].value)
                v.offer = prices[0].value
            elif sender != "vendor" and prices:
                v.last_counter = prices[-1].value
        v.rounds = max(0, sum(1 for t in v.conversation if t.sender == "agent") - 1)
        deal.vendors[v.vendor_id] = v
        assert self.manager is not None
        return await self._dry_run(deal, v.vendor_id, message, _DailyBudgetOnly(self.manager.deps.llm))

    async def _dry_run(self, sandbox: DealRecord, vendor_id: str, message: str, llm=None) -> dict:
        assert self.manager is not None
        deal_id = sandbox.id
        scratch = InMemoryDealStore()
        scratch.add(sandbox)
        sent: list[Outbound] = []

        async def capture(out: Outbound) -> None:
            sent.append(out)

        dry = DealManager(ManagerDeps(llm=llm or self.manager.deps.llm, store=scratch, research=self.manager.deps.research, on_send=capture))
        before = len(sandbox.vendors[vendor_id].events)
        state = await dry.run_turn(deal_id, vendor_id, message)
        v = sandbox.vendors[vendor_id]
        events = v.events[before:]
        safety = next((e.text for e in events if e.agent == "Safety Guard"), "")
        decision = next((e.text for e in reversed(events) if e.agent == "Strategy"), "")
        blocked = v.status == "blocked"
        if state.get("outcome") == "ignored":
            reason = f"This chat is already {'blocked' if blocked else 'done'}, so the agent would only save the message and not reply."
        elif blocked:
            reason = safety or "The message was blocked by the Safety Guard."
        else:
            reason = " ".join(x for x in (safety, decision) if x) or "The agent handled it as a normal message."
        return {"blocked": blocked, "reason": reason, "reply": sent[-1].text if sent else None, "replies": [o.text for o in sent]}

    async def retry_research(self, deal_id: str) -> bool:
        """Search the market price again (it uses search credits) and let every open vendor continue. False if there is a price already."""
        assert self.manager is not None
        deal = await self.store.get(deal_id)
        if deal.research is not None and deal.research.available:
            return False
        deal.research = None
        await self.store.save(deal)
        open_vendors = [vid for vid, v in deal.vendors.items() if v.status not in ("closed", "blocked")]
        await asyncio.gather(*(self.manager.run_turn(deal_id, vid) for vid in open_vendors))
        await self.manager.reengage(deal_id)
        return True

    async def resume_vendor(self, vendor_id: str) -> None:
        """After a restart: finish what this vendor was waiting for. Safe to call twice (it does nothing if all is done)."""
        assert self.manager is not None and self.find_deal is not None
        deal_id = await self.find_deal(vendor_id)
        if deal_id is None:
            return
        deal = await self.store.get(deal_id)
        v = deal.vendors.get(vendor_id)
        if v is None or v.status != "negotiating":
            return
        # Every branch re-checks its condition inside the vendor lock (the guard), because a turn may be running right now in this
        # same process (every GET of a deal calls this). Without it, a first message that was still being written was sent twice.
        if not v.conversation:  # the first message was never sent
            await self.manager.run_turn(deal_id, vendor_id, guard=lambda x: not x.conversation)
        elif v.conversation[-1].sender == "vendor":  # we never answered the vendor's last message
            last = v.conversation[-1]
            await self.manager.run_turn(
                deal_id, vendor_id, last.text, simulated=last.simulated, replay=True,
                guard=lambda x: bool(x.conversation) and x.conversation[-1].sender == "vendor" and x.conversation[-1].text == last.text,
            )  # fmt: skip
        elif v.played_by == "simulator":  # we wrote, but the fake vendor never answered
            await self._sim_reply(Outbound(deal_id, vendor_id, v.conversation[-1].text, "counter", v.last_counter))


def build_runtime(
    store: DealStore,
    deps_factory: Callable[[Runtime], ManagerDeps],
    find_deal: Callable[[str], Awaitable[str | None]] | None = None,
    delay: Callable[[], float] | None = None,
) -> Runtime:
    """Creates the Runtime and the Manager that points back at it (the Manager needs `on_send`, the Runtime needs the Manager)."""
    runtime = Runtime(store, find_deal, delay)
    runtime.attach(DealManager(deps_factory(runtime)))
    return runtime


def demo_delay() -> float:
    import random

    return reply_delay(random.Random(), "demo")
