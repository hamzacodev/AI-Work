from app.evals.judge import JudgeScores, grade_chat, judge_deals
from app.evals.scenarios import build_scenarios
from app.evals.transcript import DealTranscript, VendorTranscript


class FakeJudge:
    def __init__(self, scores):
        self.scores, self.calls = scores, 0

    async def complete_json(self, role, system, user, schema, deal_id=None):
        self.calls += 1
        assert "<" in user or "chat" in user  # the chat is wrapped as untrusted data
        assert "800" not in system  # the judge prompt never carries a maximum price
        return JudgeScores(**self.scores)


CHAT = [("vendor", "Hi, price is $800"), ("agent", "Hello, could you do $700?"), ("vendor", "how are you?"), ("agent", "I am good, thanks!")]


async def test_a_chat_is_graded_and_a_short_one_is_skipped():
    j = FakeJudge({"natural": 4, "relevance": 5, "patience": 3, "variety": 4, "note": "none"})
    assert (await grade_chat(CHAT, j)).natural == 4
    assert await grade_chat(CHAT[:2], j) is None and j.calls == 1


async def test_the_summary_is_a_share_of_the_best_score_and_names_the_worst_chats():
    scn = build_scenarios(1)[0]
    d = DealTranscript(scn, "safety_on", [VendorTranscript("Vendor A", "friendly", messages=CHAT)])
    out = await judge_deals([d], FakeJudge({"natural": 4, "relevance": 4, "patience": 4, "variety": 4, "note": "repeats"}), "m")
    assert out["n_graded"] == 1 and out["mean"] == 0.8 and out["criteria"]["natural"] == 0.8 and out["worst"][0]["note"] == "repeats"


def test_the_scenarios_cover_the_chatty_vendor_and_the_new_products():
    s = build_scenarios(24)
    assert {x.persona for x in s} >= {"chatty", "attacker", "liar"} and len({x.product.item for x in s}) >= 7
