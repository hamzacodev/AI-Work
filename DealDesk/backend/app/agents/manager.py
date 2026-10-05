"""The Manager: the LangGraph graph that runs ONE agent turn for ONE vendor, and the DealManager that runs many.

In easy words: until now we had separate, tested parts (Safety Guard, Offer Reader, Researcher, strategy, Negotiator,
Fact Checker, Limit Checker). This file runs them in the right order, for every vendor message.

One turn (a LangGraph graph, nodes are steps, edges are arrows):

    ingest -> safety -> research -> read_message -> decide -> negotiate -> send
                 |                                     |           |
                 +-- blocked: stop                     +-- hold / needs_you / block: stop
                                                                   +-- could not write safely: stop (ask the user)

  - A turn with no vendor message (the first message, or waking a paused vendor) skips `safety` and `read_message`.
  - Every node only reads and updates the deal record. Plain code decides (strategy.py). The AI only reads and writes words.
  - The deal is saved after EVERY node (DealStore.save). The in-memory store is used for tests and the terminal chat.
    The Supabase store comes with the real API (Phase 4), so a restart can resume.
  - The agent never accepts. The most it does is stop and recommend. Only the user accepts (CLAUDE.md rule 7).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.fact_rules import Source as FactSource
from app.agents.fact_rules import Turn
from app.agents.firm_price import read_firmness
from app.agents.negotiator import ACK_TEXT, NegotiationContext, negotiate
from app.agents.offer_reader import read_offer
from app.agents.researcher import describe
from app.agents.safety_guard import check_message
from app.core.llm import LLMError
from app.core.money import format_price
from app.guardrails.prices import extract_prices, numbers_in
from app.negotiation.addons import LABELS, credit, lost_if_price_drops
from app.negotiation.strategy import (
    Decision,
    Situation,
    decide,
    is_affirmation,
    is_refusal,
    is_upset,
    next_firm_state,
    next_stall_count,
)
from app.negotiation.tracker import (
    DealSummary,
    VendorState,
    leverage_for,
    others_active,
    reengage_candidates,
    summarize,
)
from app.research.pricing import domain as site_name
from app.schemas.records import (
    DealRecord,
    DealStore,
    Event,
    Outbound,
    VendorRecord,
)
from app.schemas.research import ResearchResult

log = logging.getLogger("dealdesk.manager")

MAX_REENGAGE_PASSES = 20  # a safety stop. Every wake-up uses a round and tells a NEW number, so it ends long before


class JsonLLM(Protocol):
    async def complete_json(self, role: str, system: str, user: str, schema: type, deal_id: str | None = None): ...


@dataclass
class ManagerDeps:
    llm: JsonLLM
    store: DealStore
    research: Callable[[DealRecord], Awaitable[ResearchResult]]  # the Researcher, or a fixed answer in tests
    on_send: Callable[[Outbound], Awaitable[None]] | None = None  # delivers the message (terminal, simulator)


class TurnState(TypedDict, total=False):
    deal_id: str
    vendor_id: str
    message: str | None
    simulated: bool
    replay: bool  # the vendor message is already saved (we are retrying after a crash), so do not add it again
    safety_verdict: str
    safety_needs_user: bool
    parse_failed: bool
    no_price: bool
    offers_extra: bool
    stop: bool
    decision: Decision
    outbound: Outbound | None
    outcome: str  # blocked | held | needs_you | sent | ignored


# ---------------------------------------------------------------- helpers


def vendor_states(deal: DealRecord) -> list[VendorState]:
    """The tracker's view of every vendor. "needs_you" counts as paused: we are not texting them."""
    out = []
    for v in deal.vendors.values():
        status = "negotiating" if v.status == "negotiating" else "blocked" if v.status == "blocked" else "paused"  # closed counts as paused
        value, counted = credit(v.addons, deal.addon_values, v.offer)
        out.append(
            VendorState(v.vendor_id, v.name, v.offer, status, v.stop_reason, v.firm, v.rounds, v.last_leverage, value, tuple(LABELS[k] for k in counted))  # type: ignore[arg-type]
        )
    return out


def ceiling_of(deal: DealRecord) -> float:
    from app.guardrails.limit_checker import compute_ceiling

    return compute_ceiling(deal.max_price, deal.ceiling_ratio)


def _trusted(deal: DealRecord) -> bool:
    """A market price we may rely on and quote: found, and not low confidence (which means the prices disagree or are too few)."""
    r = deal.research
    return r is not None and r.available and r.confidence != "low"


def _median(deal: DealRecord) -> float | None:
    return deal.research.median if _trusted(deal) and deal.research is not None else None


def _counter_said_yes_to(v: VendorRecord, text: str) -> float | None:
    """If the vendor answered a plain "yes" to our last message and that message asked for our counter price, return that counter."""
    if v.last_counter is None or not is_affirmation(text):
        return None
    last = next((t for t in reversed(v.conversation[:-1]) if t.sender == "agent"), None)  # the current vendor message is already saved
    if last is None or "?" not in last.text:
        return None
    if any(abs(p.value - v.last_counter) <= 0.01 for p in extract_prices(last.text)):
        return v.last_counter
    return None


def _casual_streak(v: VendorRecord) -> int:
    """How patient the agent has been with small talk: 1 + the number of chat replies it already sent since the vendor's last price.
    The opening message and our counters are not chat replies. So the first casual vendor message gets a reply only; the way back to the price comes
    only after the vendor answered that reply (the next casual message)."""
    conv = v.conversation
    last_price = max((i for i, t in enumerate(conv) if t.sender == "vendor" and any(ch.isdigit() for ch in t.text)), default=-1)
    rest = conv[last_price + 1 :]
    replies = sum(1 for t in rest if t.sender == "agent")
    if rest and rest[0].sender == "agent":
        replies -= 1  # the opening message, or our counter to the vendor's price: neither is a reply to small talk
    return 1 + max(0, replies)


def situation_for(deal: DealRecord, v: VendorRecord, state: TurnState) -> Situation:
    r = deal.research
    usable = r is not None and r.available
    st = vendor_states(deal)
    return Situation(
        max_price=deal.max_price,
        currency=deal.currency,
        ceiling_ratio=deal.ceiling_ratio,
        max_rounds=deal.max_rounds,
        research_low=r.low if usable else None,
        research_median=r.median if usable else None,
        research_high=r.high if usable else None,
        research_confidence=r.confidence if usable else None,
        safety_verdict=state.get("safety_verdict", "ok"),
        safety_needs_user=state.get("safety_needs_user", False),
        vendor_offer=v.offer,
        offer_parse_failed=state.get("parse_failed", False),
        no_new_price=state.get("no_price", False),
        # a vendor who gives a free extra is making an offer, not saying no, even if they cannot lower the price
        refusal=state.get("no_price", False) and not state.get("offers_extra", False) and is_refusal(state.get("message") or ""),
        messages_sent=sum(1 for t in v.conversation if t.sender == "agent"),
        casual_streak=_casual_streak(v),
        upset=state.get("no_price", False) and is_upset(state.get("message") or ""),
        affirmation=state.get("no_price", False) and is_affirmation(state.get("message") or ""),
        stopped=v.status in ("paused", "needs_you"),
        offers_so_far=tuple(v.offers_so_far),
        last_counter=v.last_counter,
        rounds=v.rounds,
        stall_count=v.stall_count,
        best_other_offer=leverage_for(v.vendor_id, st, _median(deal), ceiling_of(deal)),
        last_leverage=v.last_leverage,
        others_active=others_active(v.vendor_id, st),
        firm=v.firm,
        firm_pushes=v.firm_pushes,
        offer_credit=credit(v.addons, deal.addon_values, v.offer)[0],
    )


# ---------------------------------------------------------------- the graph


def build_graph(deps: ManagerDeps):
    locks: dict[str, asyncio.Lock] = {}  # one research per deal, even when several vendors reply at once
    research_tasks: dict[str, asyncio.Task] = {}  # research started next to the safety check, awaited by the research node

    async def ensure_research(deal_id: str, vendor_id: str) -> None:
        deal = await deps.store.get(deal_id)
        v = deal.vendors[vendor_id]
        if deal.research is None:
            lock = locks.setdefault(deal.id, asyncio.Lock())
            async with lock:
                if deal.research is None:
                    try:
                        deal.research = await deps.research(deal)
                    except Exception as e:  # noqa: BLE001  (research must never crash a negotiation: the strategy asks the user instead)
                        log.warning("research failed: %s", e)
                        deal.research = ResearchResult(currency=deal.currency, available=False, reason=f"Research failed ({type(e).__name__}).")
                    text, sources = describe(deal.research)
                    v.events.append(Event("Researcher", text, sources))
        await deps.store.save(deal)

    async def load(state: TurnState) -> tuple[DealRecord, VendorRecord]:
        deal = await deps.store.get(state["deal_id"])
        return deal, deal.vendors[state["vendor_id"]]

    async def ingest(state: TurnState) -> TurnState:
        deal, v = await load(state)
        if state.get("message") and not state.get("replay"):
            v.conversation.append(Turn(sender="vendor", text=state["message"], simulated=state.get("simulated", False)))
        await deps.store.save(deal)
        return {}

    async def safety(state: TurnState) -> TurnState:
        deal, v = await load(state)
        if deal.research is None and deal.id not in research_tasks:
            # The first message of a deal needs the market price AND a safety check. They do not depend on each other, so they
            # run at the same time. If the message turns out to be an attack, the research is simply not used.
            task = asyncio.ensure_future(ensure_research(deal.id, v.vendor_id))
            research_tasks[deal.id] = task
            task.add_done_callback(lambda _t, key=deal.id: research_tasks.pop(key, None))
        res = await check_message(state["message"] or "", deps.llm, deal.id)  # type: ignore[arg-type]
        v.events.append(Event("Safety Guard", f"{res.verdict}: {res.reason}"))
        out: TurnState = {"safety_verdict": res.verdict, "safety_needs_user": res.needs_user}
        if res.verdict == "injection":
            v.status, v.stop_reason = "blocked", "injection"
            v.events.append(Event("Manager", "This vendor tried to give orders to the agent, so it is blocked. Nothing was sent."))
            out |= {"stop": True, "outcome": "blocked"}
        await deps.store.save(deal)
        return out

    async def research(state: TurnState) -> TurnState:
        task = research_tasks.get(state["deal_id"])
        if task is not None:  # already started next to the safety check: wait for it
            await asyncio.shield(task)
        await ensure_research(state["deal_id"], state["vendor_id"])  # does nothing when the research is done
        return {}

    async def read_message(state: TurnState) -> TurnState:
        deal, v = await load(state)
        text = state["message"] or ""
        # The two reads depend only on the message, so they run at the same time (each uses the model only when its rules are unsure).
        reading, firm = await asyncio.gather(
            read_offer(
                text, deps.llm, numbers_in(" ".join([deal.full_item, *deal.alt_variants, *deal.must_haves])), _median(deal) or deal.max_price, deal.id,  # type: ignore[arg-type]
                wanted_variant=deal.variant,
            ),
            read_firmness(text, deps.llm, deal.id),  # type: ignore[arg-type]
        )
        previous, new = v.offer, v.offer
        said_yes_to = _counter_said_yes_to(v, text) if reading.status == "no_price" else None
        if said_yes_to is not None:  # "yes" to "Could you do $651?": the vendor's price is now our counter (a number from our own message)
            reading = reading.model_copy(update={"status": "price", "price": said_yes_to, "reason": f"The vendor said yes to our counter, so their price is {format_price(said_yes_to, deal.currency)}."})
        if reading.status == "price" and reading.price is not None:
            new = reading.price
            if not state.get("replay"):  # a replay after a restart is the SAME message again, not the vendor repeating a price
                v.stall_count = next_stall_count(previous, new, v.stall_count)
            v.offers_so_far.append(new)
            v.offer = new
        v.events.append(Event("Offer Reader", reading.reason))
        if reading.variants:  # prices for other colors or sizes: shown to you, never used to negotiate
            v.variant_prices.update({q.variant: q.price for q in reading.variants})
            v.events.append(Event("Offer Reader", "Other variants quoted: " + ", ".join(f"{q.variant} {format_price(q.price, deal.currency)}" for q in reading.variants) + "."))
        if reading.addons:
            before = {a.key for a in v.addons}
            v.addons = [*(a for a in v.addons if a.key not in {n.key for n in reading.addons}), *reading.addons]
            new_addons = [a for a in reading.addons if a.key not in before]  # NOT `new`: that name holds the vendor's price below
            if new_addons:
                v.events.append(Event("Offer Reader", "The vendor gives free extras: " + ", ".join(LABELS[a.key] for a in new_addons) + "."))
        was_firm = v.firm
        v.firm, v.firm_pushes = next_firm_state(v.firm, firm.firm, previous, new, v.firm_pushes)
        if v.firm and not was_firm:
            v.events.append(Event("Firm Price check", firm.reason))
        await deps.store.save(deal)
        return {"parse_failed": reading.status == "unclear", "no_price": reading.status == "no_price", "offers_extra": bool(reading.addons)}

    async def decide_node(state: TurnState) -> TurnState:
        deal, v = await load(state)
        d = decide(situation_for(deal, v, state))
        v.events.append(Event("Strategy", d.reason))
        out: TurnState = {"decision": d}
        if d.action in ("block", "needs_you", "hold"):
            before_reason = v.stop_reason
            v.status = {"block": "blocked", "needs_you": "needs_you", "hold": "paused"}[d.action]  # type: ignore[assignment]
            v.stop_reason = d.stop_reason or ("injection" if d.action == "block" else None)
            if d.action == "hold" and not v.stop_reason and before_reason in ("good_price", "near_market_low", "met_counter", "confirmed"):
                v.stop_reason = before_reason  # a quiet hold after a good price keeps its reason
            v.recommendation = d.recommendation
            out |= {"stop": True, "outcome": {"block": "blocked", "needs_you": "needs_you", "hold": "held"}[d.action]}
            # A vendor wrote a good price and we stop: ask once for the requirements, then thank them once after they answer, so the
            # chat does not go silent. Not an acceptance, no number.
            said = {t.text for t in v.conversation if t.sender == "agent"}
            line = None
            if d.action != "block" and v.stop_reason in ("good_price", "near_market_low", "met_counter", "confirmed") and state.get("message"):
                line = ACK_TEXT if ACK_TEXT not in said else None
            if line:
                v.conversation.append(Turn(sender="agent", text=line))
                await deps.store.save(deal)
                if deps.on_send is not None:
                    await deps.on_send(Outbound(deal.id, v.vendor_id, line, "close", None))
                return out
        await deps.store.save(deal)
        return out

    async def negotiate_node(state: TurnState) -> TurnState:
        deal, v = await load(state)
        d = state["decision"]
        r = deal.research if _trusted(deal) else None  # no market price in the message when it is missing or low confidence
        keep = lost_if_price_drops(v.addons, deal.addon_values, d.counter_price) if d.counter_price is not None else []
        ctx = NegotiationContext(
            decision=d,
            item=deal.full_item,
            currency=deal.currency,
            max_price=deal.max_price,
            recipient=v.contact,
            vendor_contacts=frozenset(x.contact for x in deal.vendors.values()),
            conversation=list(v.conversation),
            must_haves=deal.must_haves,
            vendor_offer=v.offer,
            vendor_prices=tuple(v.offers_so_far),
            previous_counter=v.last_counter,
            rounds=v.rounds,
            max_rounds=deal.max_rounds,
            ceiling_ratio=deal.ceiling_ratio,
            research_low=r.low if r else None,
            research_median=r.median if r else None,
            research_high=r.high if r else None,
            sources=[FactSource(title=site_name(s.url) or s.title, url=s.url) for s in r.sources] if r else [],  # the site name, not a long page title
            tactics=deal.tactics.model_copy(update={"extras_items": [k for k, val in deal.addon_values.items() if val > 0]}),
            keep_addons=keep,
            address=deal.address,
            phone=deal.phone,
        )
        result = await negotiate(ctx, deps.llm, deal.id)  # type: ignore[arg-type]
        if not result.ok or not result.message:
            v.status, v.stop_reason = "needs_you", "could_not_write"
            v.events.append(Event("Negotiator", "Could not write a message that passes every check, so nothing was sent. " + " ".join(result.problems[:2])))
            await deps.store.save(deal)
            return {"stop": True, "outcome": "needs_you"}
        v.events.append(Event("Negotiator", f"Wrote a message ({result.rewrites} rewrite{'s' if result.rewrites != 1 else ''}). It passed the Fact Checker and the Limit Checker."))
        await deps.store.save(deal)
        return {"outbound": Outbound(deal.id, v.vendor_id, result.message, d.action, d.counter_price, d.leverage_price, result.followup)}

    async def send(state: TurnState) -> TurnState:
        deal, v = await load(state)
        out = state["outbound"]
        assert out is not None
        v.conversation.append(Turn(sender="agent", text=out.text))
        if out.followup:  # two messages at once: the small-talk reply, then the way back to the price
            v.conversation.append(Turn(sender="agent", text=out.followup))
        if out.action in ("counter", "leverage"):
            v.rounds += 1
            if v.firm:
                v.firm_pushes += 1
        if out.counter_price is not None:
            v.last_counter = out.counter_price
        if out.leverage_price is not None:
            v.last_leverage = out.leverage_price
        if out.action == "close":  # the polite goodbye: we stop texting this vendor, the chat stays open
            decision = state["decision"]
            v.status, v.stop_reason, v.recommendation = "paused", decision.stop_reason, decision.recommendation
        else:
            v.status, v.stop_reason, v.recommendation = "negotiating", None, None
        await deps.store.save(deal)
        if deps.on_send is not None:
            await deps.on_send(out)
            if out.followup:
                await deps.on_send(Outbound(out.deal_id, out.vendor_id, out.followup, "chat", None))
        return {"outcome": "sent"}

    def after_ingest(state: TurnState) -> str:
        return "safety" if state.get("message") else "research"

    def stop_or(next_node: str):
        return lambda state: END if state.get("stop") else next_node

    def after_research(state: TurnState) -> str:
        return "read_message" if state.get("message") else "decide"

    g = StateGraph(TurnState)
    for name, fn in [
        ("ingest", ingest), ("safety", safety), ("research", research), ("read_message", read_message),
        ("decide", decide_node), ("negotiate", negotiate_node), ("send", send),
    ]:  # fmt: skip
        g.add_node(name, fn)
    g.add_edge(START, "ingest")
    g.add_conditional_edges("ingest", after_ingest, {"safety": "safety", "research": "research"})
    g.add_conditional_edges("safety", stop_or("research"), {END: END, "research": "research"})
    g.add_conditional_edges("research", after_research, {"read_message": "read_message", "decide": "decide"})
    g.add_edge("read_message", "decide")
    g.add_conditional_edges("decide", stop_or("negotiate"), {END: END, "negotiate": "negotiate"})
    g.add_conditional_edges("negotiate", stop_or("send"), {END: END, "send": "send"})
    g.add_edge("send", END)
    return g.compile()


# ---------------------------------------------------------------- many vendors at once


class DealManager:
    """Runs turns for all vendors of a deal, wakes paused vendors when a better price appears, and writes the summary."""

    def __init__(self, deps: ManagerDeps) -> None:
        self.deps = deps
        self.graph = build_graph(deps)
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    async def run_turn(
        self,
        deal_id: str,
        vendor_id: str,
        message: str | None = None,
        simulated: bool = False,
        replay: bool = False,
        guard: Callable[[VendorRecord], bool] | None = None,
    ) -> TurnState:
        """One turn for one vendor. Turns for the same vendor never overlap.

        `guard` is checked INSIDE the vendor lock, after any turn that was already running has finished. Restart recovery uses it
        ("send the first message only if there is still none"), so recovery can never repeat what a running turn just did."""
        lock = self._locks.setdefault((deal_id, vendor_id), asyncio.Lock())
        async with lock:
            deal = await self.deps.store.get(deal_id)
            if guard is not None and not guard(deal.vendors[vendor_id]):
                return {"outcome": "skipped"}
            if deal.vendors[vendor_id].status in ("blocked", "closed"):
                # A chat is never closed. The agent just does not negotiate here any more (the deal is decided, or the vendor
                # was blocked). The message is kept and shown, and the Safety Guard still looks at it after a decided deal.
                if message and not replay:
                    await self._after_the_deal(deal, deal.vendors[vendor_id], message, simulated)
                return {"outcome": "ignored"}
            try:
                return await self.graph.ainvoke(
                    {"deal_id": deal_id, "vendor_id": vendor_id, "message": message, "simulated": simulated, "replay": replay}
                )
            except LLMError as e:  # fail closed: any model problem ends the turn and asks the user
                deal = await self.deps.store.get(deal_id)
                v = deal.vendors[vendor_id]
                v.status, v.stop_reason = "needs_you", "model_error"
                v.events.append(Event("Manager", f"The model could not be used ({type(e).__name__}), so the agent stopped and needs you."))
                await self.deps.store.save(deal)
                return {"outcome": "needs_you"}

    async def _after_the_deal(self, deal: DealRecord, v: VendorRecord, message: str, simulated: bool) -> None:
        v.conversation.append(Turn(sender="vendor", text=message, simulated=simulated))
        if v.status == "blocked":
            v.events.append(Event("Manager", "This vendor was blocked. The new message was saved, but the agent does not reply."))
        else:
            note = "The vendor wrote after the deal was decided. The agent does not negotiate any more. Read the message in the chat."
            try:
                res = await check_message(message, self.deps.llm, deal.id)  # type: ignore[arg-type]
                if res.verdict != "ok":
                    note += f" The Safety Guard flagged it: {res.verdict}. {res.reason}"
            except LLMError:
                note += " The Safety Guard could not check it, so treat it with care."
            v.events.append(Event("Manager", note))
        await self.deps.store.save(deal)

    async def start(self, deal_id: str) -> None:
        """Sends the first message to every vendor."""
        deal = await self.deps.store.get(deal_id)
        await asyncio.gather(*(self.run_turn(deal_id, vid) for vid in deal.vendors))

    async def on_vendor_message(self, deal_id: str, vendor_id: str, text: str, simulated: bool = False) -> TurnState:
        state = await self.run_turn(deal_id, vendor_id, text, simulated)
        await self.reengage(deal_id)
        return state

    async def reengage(self, deal_id: str) -> list[str]:
        """Writes again to paused vendors when ANOTHER vendor has since got a better price (the chat was never closed)."""
        woken: list[str] = []
        for _ in range(MAX_REENGAGE_PASSES):
            deal = await self.deps.store.get(deal_id)
            ids = reengage_candidates(vendor_states(deal), _median(deal), ceiling_of(deal), deal.max_rounds)
            if not ids:
                break
            results = await asyncio.gather(*(self.run_turn(deal_id, vid) for vid in ids))
            woken += ids
            if not any(r.get("outcome") == "sent" for r in results):
                break  # nobody was written to, so nothing changed and another pass would change nothing either
        return woken

    async def summary(self, deal_id: str) -> DealSummary:
        deal = await self.deps.store.get(deal_id)
        return summarize(vendor_states(deal), _median(deal), deal.currency)
