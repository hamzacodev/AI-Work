"""Negotiation tactics: the buyer's PLAYBOOK. Plain data and rules, no AI.

Real buyers use a few moves, and different moves in different rounds: a reason to lower the price, a hint of more
business, a request for extras, a willingness to meet halfway. This file is that playbook.

CODE chooses the move for each round and the EXACT sentence. The AI only writes the words around it. Every sentence
here is checked by the Fact Checker as an approved sentence, so nothing is invented. Two kinds of move:

  CLAIMS (a promise, or something about the buyer). Off by default. The buyer ticks what is TRUE for this deal:
      buy more than one, buy again, a friend may also want one, can decide today, will keep looking.
  REQUESTS and process lines (a question, or a plain statement of how the buyer negotiates). On by default:
      ask for the best price, ask for extras such as free delivery, "I can move a little if you do too".

The agent never names a person, never promises more than approved, and always words claims as conditions.
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.negotiation.addons import words

_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}

# Which move to try in which round (0 = the first counter). The first one the buyer allows is used.
PLAYBOOK: dict[int, tuple[str, ...]] = {
    0: ("quantity", "refer", "again", "decide_today"),
    1: ("refer", "again", "decide_today", "extras", "best_price", "quantity"),
    2: ("meet_halfway", "keep_looking", "extras", "again", "best_price"),
}
# One rapport line per round: the "we came to you hoping for a rate better than the market" idea, worded a little
# differently each time. They only state what the buyer hopes for. They say nothing untrue about the vendor.
RAPPORT = (
    "I came to you hoping for a rate better than the market.",
    "We thought you would give us a better rate than the market.",
    "We were hoping to buy from you at a rate below the market.",
)
DEFAULT_ORDER = ("quantity", "refer", "again", "decide_today", "extras", "best_price", "meet_halfway", "keep_looking")


@dataclass(frozen=True)
class Move:
    id: str
    sentence: str
    note: str  # told to the Fact Checker's model, so it knows this is approved


class Tactics(BaseModel):
    good_rate_line: bool = True  # "I came to you because I want a good rate." Only says what the buyer wants.
    # claims: off by default, the buyer ticks what is true
    may_buy_quantity: int = Field(default=1, ge=1, le=20)  # how many units the buyer really may buy (1 = just one)
    may_buy_again: bool = False
    may_refer: bool = False  # a friend or family member may also want one
    can_decide_today: bool = False
    keep_looking: bool = False  # the buyer really will keep looking if there is no deal
    # requests and process lines: on by default
    ask_best_price: bool = True
    ask_extras: bool = True
    meet_halfway: bool = True
    extras_items: list[str] = Field(default_factory=list)  # keys of the free extras the buyer values (addons.py). Set from the deal.

    # ------------------------------------------------------------ the moves

    def moves(self) -> dict[str, Move]:
        """Every move that is currently allowed, with its exact sentence."""
        m: dict[str, Move] = {}
        if self.may_buy_quantity > 1:
            n = _NUMBER_WORDS.get(self.may_buy_quantity, str(self.may_buy_quantity))
            m["quantity"] = Move(
                "quantity", f"If we agree a good price, I would buy {n}.",
                f"If the price is good the buyer may buy up to {self.may_buy_quantity} units. Only as a condition.",
            )  # fmt: skip
        if self.may_refer:
            m["refer"] = Move(
                "refer", "If the price is good, a friend of mine may also want one.",
                "A friend or family member may also want to buy one. Only as a condition, and never name them.",
            )  # fmt: skip
        if self.may_buy_again:
            m["again"] = Move(
                "again", "If this goes well, I would be happy to buy from you again.",
                "If the deal goes well the buyer may buy from this vendor again. Only as a condition.",
            )  # fmt: skip
        if self.can_decide_today:
            m["decide_today"] = Move(
                "decide_today", "If we can agree on a price, I can decide today.",
                "The buyer can decide quickly if the price is right. Only as a condition.",
            )  # fmt: skip
        if self.ask_extras:
            sentence = (
                f"Could you also include the {words(self.extras_items)} at that price?"
                if self.extras_items
                else "Could you also include free delivery or the charger at that price?"
            )
            m["extras"] = Move("extras", sentence, "The buyer may ask for extras such as a charger or free delivery. This is a request, not a claim.")
        if self.ask_best_price:
            m["best_price"] = Move("best_price", "Is that the best price you can do?", "The buyer may ask whether this is the best price. This is a question.")
        if self.meet_halfway:
            m["meet_halfway"] = Move(
                "meet_halfway", "I can move a little if you can come down a bit too.",
                "The buyer may raise the offer a little in later rounds if the vendor also comes down.",
            )  # fmt: skip
        if self.keep_looking:
            m["keep_looking"] = Move(
                "keep_looking", "If we cannot agree on a price, I will keep looking at other listings.",
                "The buyer will keep looking at other listings if there is no deal. Only as a condition.",
            )  # fmt: skip
        return m

    def rapport_for_round(self, round_index: int) -> str | None:
        """The "better than the market" sentence for this round, or None if the buyer switched it off."""
        return RAPPORT[round_index % len(RAPPORT)] if self.good_rate_line else None

    def required_sentences(self, round_index: int, said: tuple[str, ...] = ()) -> list[str]:
        """The sentences the draft MUST contain this round. A real buyer does not repeat the same lines every message, so:
        the "better than the market" line only opens the first counter, and a playbook move is never used twice in a conversation.
        `said` is what the agent already wrote to this vendor."""
        before = " ".join(" ".join(x.lower().split()) for x in said)
        rapport = self.rapport_for_round(round_index) if round_index == 0 else None
        line = self.line_for_round(round_index, before)
        return [x for x in (rapport, line) if x and " ".join(x.lower().split()) not in before]

    def persuasion_lines(self) -> list[str]:
        """Every exact sentence the buyer allowed. The Fact Checker accepts these word for word."""
        lines = list(RAPPORT) if self.good_rate_line else []
        return lines + [mv.sentence for mv in self.moves().values()]

    def line_for_round(self, round_index: int, said: str = "") -> str | None:
        """The sentence the draft MUST contain in this round, or None. Code decides, the AI only words around it.
        A move whose sentence was already said (`said`, lower case) is skipped, so the buyer never repeats a line."""
        allowed = self.moves()
        fresh = lambda sentence: " ".join(sentence.lower().split()) not in said
        if round_index not in PLAYBOOK:  # beyond the playbook, take turns through whatever is allowed and not used yet
            usable = [allowed[i].sentence for i in DEFAULT_ORDER if i in allowed and fresh(allowed[i].sentence)]
            return usable[round_index % len(usable)] if usable else None
        for move_id in PLAYBOOK[round_index]:
            if move_id in allowed and fresh(allowed[move_id].sentence):
                return allowed[move_id].sentence
        return None

    # ------------------------------------------------------------ for the Fact Checker and the prompt

    def approved_notes(self) -> list[str]:
        """Sentences for the Fact Checker's list of approved facts."""
        notes = []
        if self.good_rate_line:
            notes.append("The buyer hopes this vendor will give a rate better than the market. This may be said as a reason.")
        notes += [mv.note for mv in self.moves().values()]
        return notes

    def prompt_lines(self) -> list[str]:
        """What the Negotiator may use, in words for its prompt."""
        lines = []
        lines += [f'You may say: "{s}"' for s in self.persuasion_lines()]
        return lines
