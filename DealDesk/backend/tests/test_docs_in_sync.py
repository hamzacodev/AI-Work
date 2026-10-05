"""AGENT_EXECUTION_FLOW.md must describe the code that exists. These tests fail when it drifts."""

import ast
import re
from pathlib import Path

from app.agents import researcher
from app.agents.manager import ManagerDeps, build_graph
from app.core import llm as llm_module
from app.core.config import Settings
from app.schemas.records import InMemoryDealStore

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "AGENT_EXECUTION_FLOW.md").read_text()
APP = ROOT / "backend" / "app"


def test_every_node_of_the_vendor_turn_graph_is_in_the_document():
    graph = build_graph(ManagerDeps(llm=None, store=InMemoryDealStore(), research=None))  # type: ignore[arg-type]
    nodes = [n for n in graph.get_graph().nodes if not n.startswith("__")]
    assert nodes, "the graph has no nodes?"
    missing = [n for n in nodes if f"**{n}**" not in DOC]
    assert missing == [], f"graph nodes missing from AGENT_EXECUTION_FLOW.md: {missing}"


def test_every_agent_that_calls_the_model_is_in_the_document():
    names = set()
    for path in APP.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "llm_label" and node.args and isinstance(node.args[0], ast.Constant):
                names.add(node.args[0].value)
    assert names, "no llm_label calls found?"
    missing = sorted(n for n in names if n not in DOC)
    assert missing == [], f"agents that call the model but are missing from AGENT_EXECUTION_FLOW.md: {missing}"


def test_the_models_and_roles_in_the_document_are_the_ones_in_the_settings():
    s = Settings(_env_file=None)
    prod = Settings(_env_file=None, app_env="production", groq_api_key="x")
    for model in {s.llm_model_main, s.llm_model_fast, prod.llm_model_main, prod.llm_model_fast, prod.llm_model_fallback}:
        assert model in DOC, f"model {model} is not in AGENT_EXECUTION_FLOW.md"
    assert "`fast`" in DOC and "`main`" in DOC


def test_the_limits_in_the_document_match_the_code():
    assert f"up to {researcher.MAX_QUERIES} queries" in DOC or f"up to {researcher.MAX_QUERIES} " in DOC
    assert f"up to {llm_module.JSON_RETRIES} retries" in DOC
    assert "1 s, 2 s, 4 s, 8 s" in DOC and llm_module.RATE_LIMIT_RETRIES == 4
    assert str(Settings(_env_file=None).daily_llm_call_budget) in DOC and str(Settings(_env_file=None).max_llm_calls_per_deal) in DOC


def test_every_file_the_document_names_exists():
    named = set(re.findall(r"`((?:agents|negotiation|guardrails|research|core|api|schemas|simulator)/[a-z_/]+\.py)`", DOC))
    assert named, "the document names no files?"
    missing = sorted(p for p in named if not (APP / p).exists())
    assert missing == [], f"files named in AGENT_EXECUTION_FLOW.md that do not exist: {missing}"


def test_the_diagrams_are_well_formed():
    assert DOC.count("```") % 2 == 0
    blocks = re.findall(r"```mermaid\n(.*?)```", DOC, re.DOTALL)
    assert len(blocks) >= 6
    for b in blocks:
        assert b.lstrip().startswith(("flowchart", "sequenceDiagram")), b[:40]
        assert b.count("[") == b.count("]") and b.count("(") == b.count(")") and b.count('"') % 2 == 0


def test_the_changelog_and_the_update_rule_are_there():
    assert "## Changelog" in DOC and "How to keep this file true" in DOC and "docs/TOKEN_USAGE.md" in DOC


ARCH = (ROOT / "architecture.mmd").read_text()


def test_the_architecture_diagram_names_every_agent_and_service_that_exists():
    for name in ("Safety Guard", "Researcher", "Offer Reader", "Firm Price", "Strategy", "Negotiator", "Fact Checker", "Limit Checker",
                 "Closer", "Assistant", "Manager", "Runtime", "Ollama", "Groq", "Supabase", "Tavily"):
        assert name in ARCH, f"{name} is missing from architecture.mmd"
    assert ARCH.lstrip().startswith("flowchart")
    assert ARCH.count("[") == ARCH.count("]") and ARCH.count("(") == ARCH.count(")") and ARCH.count('"') % 2 == 0
    assert ARCH.count("subgraph") == ARCH.count("\n    end") + ARCH.count("\n        end")
