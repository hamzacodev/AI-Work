# SecScout

## What it is
SecScout finds security gaps in apps, ranks them, proposes fixes and checks that the
fixes work. It only runs on repos I own and on practice apps (OWASP Juice Shop,
NodeGoat), always inside a Docker sandbox. A human approves before any change.
Free tools only.

## Project type
Agentic AI project built with LangGraph.

## The 5 agents (not built yet)
1. **Scanner** - runs the security tools on a target.
2. **Analyst** - reads the findings and removes noise.
3. **Prioritizer** - ranks the findings by risk.
4. **Fixer** - proposes a fix for each finding.
5. **Verifier** - re-checks that the fix works and breaks nothing.

## Tech stack
Python, LangGraph, FastAPI, Groq, Ollama, Semgrep, npm audit, Gitleaks, Docker,
SQLite, Next.js, TypeScript, pytest.

## How to run
```
uv sync
cp .env.example .env     # then fill in your own keys
uv run pytest
uv run ruff check .
```
Agents are not built yet, so there is nothing else to run.

## Safety rules
See [docs/safety-rules.md](docs/safety-rules.md). Practice apps are listed in
[docs/targets.md](docs/targets.md).
