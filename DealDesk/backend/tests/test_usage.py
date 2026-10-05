import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings
from app.core.llm import (
    LLM,
    UsageLog,
    UsageRecord,
    estimate_cost,
    estimate_tokens,
    llm_label,
    usage_log,
)
from main import app


class Answer(BaseModel):
    price: float
    note: str


def reply(text, prompt=None, completion=None, cached=None):
    usage = None
    if prompt is not None:
        details = SimpleNamespace(cached_tokens=cached) if cached is not None else None
        usage = SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion, prompt_tokens_details=details)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=usage)


class Client:
    def __init__(self, results):
        self.results = list(results)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        return self.results.pop(0)


async def no_sleep(_):
    return None


def make(client, provider="ollama", main="llama3.1:8b", fast="llama3.1:8b"):
    s = Settings(_env_file=None, llm_provider=provider, llm_model_main=main, llm_model_fast=fast, llm_model_fallback=fast)
    return LLM(s, client=client, sleep=no_sleep)


@pytest.fixture(autouse=True)
def clean_log():
    usage_log.records.clear()
    old = usage_log.path
    usage_log.path = ""
    yield
    usage_log.records.clear()
    usage_log.path = old


async def test_the_hosts_own_token_counts_are_recorded_for_a_local_model():
    llm = make(Client([reply('{"price": 1, "note": "x"}', prompt=480, completion=22)]))
    with llm_label("Offer Reader", "choose the price"):
        await llm.complete_json("fast", "Pick the price.", "message", Answer, deal_id="d1")
    (r,) = usage_log.records
    assert (r.agent, r.purpose, r.role, r.model, r.provider, r.local) == ("Offer Reader", "choose the price", "fast", "llama3.1:8b", "ollama", True)
    assert (r.prompt_tokens, r.completion_tokens, r.total_tokens, r.estimated, r.deal_id, r.tool_tokens, r.cost_usd) == (480, 22, 502, False, "d1", 0, 0.0)


async def test_the_prompt_is_split_into_parts_that_add_up():
    llm = make(Client([reply('{"price": 1, "note": "x"}', prompt=1000, completion=10)]))
    history = "VENDOR: hello there. BUYER: hi."
    with llm_label("Negotiator", "write a counter message", history=history):
        await llm.complete_json("main", "S" * 400, "U" * 200 + history, Answer)
    (r,) = usage_log.records
    parts = r.system_tokens_est + r.schema_tokens_est + r.user_tokens_est + r.history_tokens_est + r.retry_tokens_est
    assert abs(parts - 1000) <= 3  # rounding only
    assert r.schema_tokens_est > 0 and r.history_tokens_est > 0 and r.retry_tokens_est == 0


async def test_cloud_calls_get_a_list_price_cost_and_a_cache_count():
    llm = make(Client([reply('{"price": 1, "note": "x"}', prompt=2000, completion=100, cached=500)]), provider="groq", main="llama-3.3-70b-versatile", fast="llama-3.3-70b-versatile")
    await llm.complete_json("main", "s", "u", Answer)
    (r,) = usage_log.records
    assert r.provider == "groq" and r.local is False and r.cached_tokens == 500
    assert r.cost_usd == pytest.approx((1500 * 0.59 + 100 * 0.79) / 1_000_000)


def test_costs():
    assert estimate_cost("ollama", "llama3.1:8b", 1000, 100) == 0.0
    assert estimate_cost("groq", "llama-3.1-8b-instant", 1_000_000, 1_000_000) == pytest.approx(0.13)
    assert estimate_cost("groq", "some-new-model", 1000, 1000) == 0.0  # unknown price: zero, never a made-up number


async def test_when_the_host_reports_nothing_the_counts_are_estimates_and_say_so():
    llm = make(Client([reply('{"price": 1, "note": "x"}')]))
    await llm.complete_json("fast", "a" * 400, "b" * 400, Answer)
    (r,) = usage_log.records
    assert r.estimated is True and r.prompt_tokens > 200 and r.completion_tokens > 0


async def test_every_retry_after_bad_json_is_its_own_record_with_retry_tokens():
    llm = make(Client([reply("not json", 100, 5), reply('{"price": 3, "note": "n"}', 160, 8)]))
    with llm_label("Safety Guard", "check"):
        await llm.complete_json("fast", "s", "u", Answer)
    first, second = usage_log.records
    assert (first.attempt, second.attempt) == (1, 2) and first.retry_tokens_est == 0 and second.retry_tokens_est > 0


async def test_calls_without_a_label_are_marked_unlabelled():
    await make(Client([reply('{"price": 1, "note": "x"}', 10, 2)])).complete_json("fast", "s", "u", Answer)
    assert usage_log.records[0].agent == "unlabelled"


async def test_plain_text_calls_are_recorded_too():
    await make(Client([reply("hello", 12, 3)])).complete("fast", "s", "u")
    assert usage_log.records[0].json_mode is False and usage_log.records[0].total_tokens == 15


def test_estimate_tokens():
    assert estimate_tokens("") == 0 and estimate_tokens("abcd") == 1 and estimate_tokens("abcde") == 2


async def test_the_log_is_written_to_a_file_with_counts_only(tmp_path):
    usage_log.path = str(tmp_path / "usage" / "llm.jsonl")
    llm = make(Client([reply('{"price": 1, "note": "SECRET ANSWER"}', 50, 5)]))
    await llm.complete_json("fast", "SECRET PROMPT", "SECRET USER", Answer)
    text = Path(usage_log.path).read_text()
    assert json.loads(text.splitlines()[0])["total_tokens"] == 55
    assert "SECRET" not in text  # prompts and answers are never stored


def test_a_disk_that_cannot_be_written_never_breaks_a_call(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("x")
    log = UsageLog(path=str(blocked / "child" / "x.jsonl"))  # a file where a folder is needed
    log.add(UsageRecord("t", None, "a", "p", "fast", "m", "ollama", True, 1, 1, 2, None, 1, 0, 0, 0, 0, 0, 0.0, 1, False))
    assert len(log.records) == 1


async def test_the_summary_adds_up_by_agent():
    llm = make(Client([reply('{"price": 1, "note": "x"}', 100, 10), reply('{"price": 1, "note": "x"}', 200, 20), reply('{"price": 1, "note": "x"}', 50, 5)]))
    for agent in ("A", "A", "B"):
        with llm_label(agent, "p"):
            await llm.complete_json("fast", "s", "u", Answer)
    s = usage_log.summary()
    assert s["by_agent"]["A"]["calls"] == 2 and s["by_agent"]["A"]["total_tokens"] == 330 and s["total"]["calls"] == 3 and s["total"]["total_tokens"] == 385


def test_the_usage_endpoint():
    usage_log.add(UsageRecord("t", None, "Safety Guard", "p", "fast", "m", "ollama", True, 10, 2, 12, None, 5, 0, 5, 0, 0, 0, 0.0, 1, False))
    body = TestClient(app).get("/usage").json()
    assert body["total"]["calls"] == 1 and body["by_agent"]["Safety Guard"]["total_tokens"] == 12 and len(body["recent"]) == 1
    assert TestClient(app).get("/usage?recent=0").json()["recent"] == []


# ---------------------------------------------------------------- the guard: no model call may go unrecorded under a name


def test_every_model_call_in_the_app_sits_inside_an_llm_label_block():
    """If you add a model call without a label, the usage report would show it as 'unlabelled' and the docs would drift."""
    offenders = []
    for path in Path("app").rglob("*.py"):
        if path.as_posix() == "app/core/llm.py":
            continue
        tree = ast.parse(path.read_text())
        parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("complete_json", "complete"):
                if not isinstance(node.func.value, (ast.Name, ast.Attribute)) or "llm" not in ast.unparse(node.func.value).lower():
                    continue
                cur, ok = node, False
                while cur in parents:
                    cur = parents[cur]
                    if isinstance(cur, ast.With) and any("llm_label" in ast.unparse(i.context_expr) for i in cur.items):
                        ok = True
                        break
                if not ok:
                    offenders.append(f"{path}:{node.lineno}")
    assert offenders == []
