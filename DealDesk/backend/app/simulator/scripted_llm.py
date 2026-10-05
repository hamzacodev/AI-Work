"""A stand-in for the language model, for demos and rehearsals. It needs no model, no network and no key.

It plays every model role the agent uses: it says "ok" to the Safety Guard, supports every statement for the Fact Checker,
and writes a correct (plain) buyer message from the instructions in the prompt. The REAL checks still run on what it
writes: the number check, the Fact Checker rules and the Limit Checker. Only the wording is canned.
Used by scripts/chat_as_vendor.py --no-model and scripts/dev_server_memory.py. Never used in the real product.
"""

import re

from app.agents.assistant import IntentOut, Slots
from app.agents.fact_checker import FactVerdict, StatementVerdict
from app.agents.firm_price import FirmVerdict
from app.agents.negotiator import Draft
from app.agents.offer_reader import OfferChoice, OtherVariant, VariantChoice
from app.agents.safety_guard import ModelVerdict
from app.schemas.records import DealRecord
from app.schemas.research import ResearchResult, Source

_COLORS = r"black|white|gr[ae]y|silver|gold|blue|red|green|pink|purple|yellow|maroon|orange|midnight|titanium"


def _read_purchase(text: str) -> Slots:
    """A rough stand-in for the model that reads a purchase request. The REAL checks (verify_slots) still run on what it returns."""
    m = re.search(r"(?:buy|get|purchase|order|find|price\s+of|looking\s+for)\s+(?:me\s+)?(?:a\s+|an\s+|the\s+)?(.+?)(?:\s+(?:under|below|for|with|in|up\s+to|at\s+most|max|around)\b|[,.$]|$)", text, re.IGNORECASE)
    item = re.sub(rf"\b(?:{_COLORS})\b|\b\d+\s?(?:gb|tb)\b", "", m.group(1), flags=re.IGNORECASE).strip() if m else ""
    variant = ", ".join(re.findall(rf"\b(?:{_COLORS})\b|\b\d+\s?(?:gb|tb)\b", text, re.IGNORECASE))
    must = [x.strip() for x in re.findall(r"\bwith\s+(.+?)(?:\s+under\b|[,.]|$)", text, re.IGNORECASE)]
    return Slots(item=item, variant=variant, must_haves=must)


class ScriptedLLM:
    async def complete_json(self, role, system, user, schema, deal_id=None):
        if schema is IntentOut:
            return IntentOut(intent="chat")
        if schema is Slots:
            return _read_purchase(user)
        if schema is ModelVerdict:
            return ModelVerdict(verdict="ok", reason="Normal message.")
        if schema is VariantChoice:  # a rehearsal stand-in: the first price is the wanted variant, the rest are "other variants"
            n = len(re.findall(r"^(\d+)\) ", user, re.MULTILINE))
            return VariantChoice(choice=1 if n else 0, others=[OtherVariant(choice=i, variant=f"other variant {i - 1}") for i in range(2, n + 1)])
        if issubclass(schema, OfferChoice):
            return OfferChoice(choice=0)
        if schema is FirmVerdict:
            return FirmVerdict(firm=False)
        if schema is FactVerdict:
            return FactVerdict(
                statements=[StatementVerdict(statement=int(n), supported=True, problem="") for n, _ in re.findall(r"^(\d+)\. (.*)$", user, re.MULTILINE)]
            )
        if "FIRST message" in system:
            return Draft(message="Hello, I am interested in the Dell XPS 15 with 16GB RAM. What is your best price?")
        parts = [x for line in system.splitlines() if "word for word" in line for x in re.findall(r'"([^"]+)"', line)]
        counter = re.search(r"counter offer of exactly (\$[\d,]+(?:\.\d+)?)", system)
        parts.append(f"Could you do {counter.group(1)}?" if counter else "Can you do better than that?")
        return Draft(message=" ".join(parts))


async def fixed_research(deal: DealRecord) -> ResearchResult:
    """A fixed market price (about 0.875 of the buyer's maximum around the median), so no search credits are spent."""
    median = round(deal.max_price * 0.875)
    return ResearchResult(
        currency=deal.currency, low=round(median * 0.91), median=median, high=round(median * 1.13), n_sources=3, regions=["US", "UK"],
        confidence="medium", available=True, note="Fixed demo price. Not from the web.",
        sources=[Source(title="Demo retailer", url="https://a.example.com", price=median, region="US")],
    )  # fmt: skip
