# DealDesk progress

<!-- PROGRESS-BAR:START -->

## Progress

```text
PROJECT  [████████████████████████]  99.4%   (0.6% left)
```

**By phase** (each phase counts by its size)

```text
Phase 0  Setup                            [████████████████████████] 100.0%   (worth 5.26%)
Phase 1a Frontend with mock data          [████████████████████████] 100.0%   (worth 15.79%)
Phase 1b Pipeline and first deploy        [████████████████████████] 100.0%   (worth 7.368%)
Phase 2  Backend core                     [████████████████████████] 100.0%   (worth 18.948%)
Phase 3  Agents and research              [████████████████████████] 100.0%   (worth 25.265%)
Phase 4  Connect the real frontend        [████████████████████████] 100.0%   (worth 9.474%)
Phase 5  Evaluation and scorecard         [████████████████████████] 100.0%   (worth 8.422%)
Phase 6  Hardening and README             [████████████████████████] 100.0%   (worth 5.263%)
Phase 7  Hosted model and final deploy    [████████████████████░░░░]  85.0%   (worth 4.21%)
```

**By module** (each part of the system, across all phases)

```text
Setup and accounts           [████████████████████████] 100.0%
Frontend                     [████████████████████████] 100.0%
Backend API and data         [████████████████████████] 100.0%
Models and LLM layer         [████████████████████████] 100.0%
Deployment and operations    [██████████████████████░░]  92.5%
Safety guards                [████████████████████████] 100.0%
Testing and evaluation       [████████████████████████] 100.0%
Research                     [████████████████████████] 100.0%
Negotiation and agent        [████████████████████████] 100.0%
```

**Phase table**

| Phase | What | Status | Done | Worth |
|---|---|---|---|---|
| 0 | Setup | ✅ Done | 100% | 5.26% |
| 1a | Frontend with mock data | ✅ Done | 100% | 15.79% |
| 1b | Pipeline and first deploy | ✅ Done | 100% | 7.368% |
| 2 | Backend core | ✅ Done | 100% | 18.948% |
| 3 | Agents and research | ✅ Done | 100% | 25.265% |
| 4 | Connect the real frontend | ✅ Done | 100% | 9.474% |
| 5 | Evaluation and scorecard | ✅ Done | 100% | 8.422% |
| 6 | Hardening and README | ✅ Done | 100% | 5.263% |
| 7 | Hosted model and final deploy | 🟡 In progress · 🟣 Needs you | 85% | 4.21% |

**Module table**

| Module | Status | Done |
|---|---|---|
| Setup and accounts | ✅ Done | 100% |
| Frontend | ✅ Done | 100% |
| Backend API and data | ✅ Done | 100% |
| Models and LLM layer | ✅ Done | 100% |
| Deployment and operations | 🟡 In progress · 🟣 Needs you | 92% |
| Safety guards | ✅ Done | 100% |
| Testing and evaluation | ✅ Done | 100% |
| Research | ✅ Done | 100% |
| Negotiation and agent | ✅ Done | 100% |

**Every task**

| Phase | Module | Task | Status | Size | Done |
|---|---|---|---|---|---|
| 0 | Setup and accounts | Tools, repo, env files, accounts | ✅ Done | 5.26% | 100% |
| 1a | Frontend | Design, nav, login, Home, Planned pages | ✅ Done | 4.211% | 100% |
| 1a | Frontend | Buy page with CSV and Excel upload | ✅ Done | 3.158% | 100% |
| 1a | Frontend | Deals screen, chat, decision card, trick box | ✅ Done | 5.263% | 100% |
| 1a | Frontend | WhatsApp demonstration, Scorecard, API client | ✅ Done | 3.158% | 100% |
| 1b | Backend API and data | FastAPI app, settings, CORS, health | ✅ Done | 1.579% | 100% |
| 1b | Backend API and data | Supabase schema and connection | ✅ Done | 1.579% | 100% |
| 1b | Models and LLM layer | LLM layer on Ollama | ✅ Done | 2.105% | 100% |
| 1b | Deployment and operations | First deploy of frontend and backend | ✅ Done | 2.105% | 100% |
| 2 | Backend API and data | Deal schemas and create/get endpoints | ✅ Done | 2.105% | 100% |
| 2 | Safety guards | Limit Checker (plain code) | ✅ Done | 4.211% | 100% |
| 2 | Safety guards | Safety Guard (rules plus model) | ✅ Done | 3.684% | 100% |
| 2 | Safety guards | Fact Checker (rules, filter, model, rewrite loop) | ✅ Done | 4.211% | 100% |
| 2 | Testing and evaluation | Simulator with 5 fake vendors and 30 attacks | ✅ Done | 2.632% | 100% |
| 2 | Deployment and operations | Budget, rate limit, leases and resume | ✅ Done | 2.105% | 100% |
| 3 | Research | Researcher (search, verified extraction, FX, pricing, cache) | ✅ Done | 4.211% | 100% |
| 3 | Negotiation and agent | Counter formula and decision (plain code) | ✅ Done | 3.158% | 100% |
| 3 | Negotiation and agent | Tactics playbook (round by round) in the Fact Checker | ✅ Done | 1.053% | 100% |
| 3 | Negotiation and agent | Negotiator (AI writes the reply) | ✅ Done | 4.211% | 100% |
| 3 | Negotiation and agent | Understand-the-offer step | ✅ Done | 2.105% | 100% |
| 3 | Negotiation and agent | Best Offer Tracker, leverage line, firm price and pause rule | ✅ Done | 1.053% | 100% |
| 3 | Negotiation and agent | LangGraph agent loop | ✅ Done | 4.211% | 100% |
| 3 | Negotiation and agent | Variants (color, size) and free extras, effective price | ✅ Done | 2.105% | 100% |
| 4 | Negotiation and agent | Chats never close, Assistant chat starts new purchases | ✅ Done | 2.105% | 100% |
| 4 | Testing and evaluation | Token tracking, AGENT_EXECUTION_FLOW.md, first token optimizations | ✅ Done | 1.053% | 100% |
| 3 | Negotiation and agent | Closer (after you accept) | ✅ Done | 1.579% | 100% |
| 3 | Backend API and data | Decision endpoint | ✅ Done | 1.053% | 100% |
| 3 | Backend API and data | /parse-request and /trick endpoints | ✅ Done | 0.526% | 100% |
| 4 | Frontend | Take-control screen (on demo data) | ✅ Done | 1.053% | 100% |
| 4 | Backend API and data | Take-control and tester-message endpoints | ✅ Done | 1.053% | 100% |
| 4 | Frontend | Replace mock data with the real API | ✅ Done | 2.105% | 100% |
| 4 | Negotiation and agent | Full Buy flow works end to end on Ollama | ✅ Done | 1.579% | 100% |
| 4 | Frontend | Buyer request box on the WhatsApp page | ✅ Done | 0.526% | 100% |
| 5 | Testing and evaluation | Scenarios and judge | ✅ Done | 3.158% | 100% |
| 5 | Testing and evaluation | Evaluation runner | ✅ Done | 2.632% | 100% |
| 5 | Testing and evaluation | Full run stored, real Scorecard, attack tests | ✅ Done | 2.632% | 100% |
| 6 | Frontend | Error, empty and loading states, waking-up message | ✅ Done | 2.105% | 100% |
| 6 | Deployment and operations | README with architecture diagram | ✅ Done | 2.105% | 100% |
| 6 | Safety guards | Security check: secrets, CORS, limits | ✅ Done | 1.053% | 100% |
| 7 | Models and LLM layer | Switch to a hosted model, smoke test | ✅ Done | 2.105% | 100% |
| 7 | Deployment and operations | Redeploy, test in a fresh browser and on a phone | 🟡 In progress · 🟣 Needs you | 2.105% | 70% |

**Blockers and things that wait on you**

| Flag | Phase | What | Note |
|---|---|---|---|
| 🟣 Needs you | 3 | Check that Tavily pay-as-you-go is switched off | Keeps the research tier free |
| 🟣 Needs you | 7 | Redeploy, test in a fresh browser and on a phone | You test on your phone and in a fresh browser |

Key: ✅ done, 🟡 in progress, 🟠 not started, 🔴 blocked, 🟣 needs you (shown after the status).

_Drawn by `python3 scripts/progress.py` from `progress.json`. Edit that file, then run the script. Sizes are estimates._

<!-- PROGRESS-BAR:END -->

Status key: Done, In progress, To do. Phases come from CLAUDE.md section 9. The bars above are drawn from `progress.json`.

**Last step done (4 Oct 2026, from your live tests):** (00000) A light and a dark theme with a new blue palette and a dashboard look (sidebar card, round theme button, dark pill buttons, soft shadows), all colors as tokens, readability checked in both themes. (0000) Secret check: no key is in git, its history, the website build or any live API answer. A new `scripts/check_secrets.py`, a pre-commit hook and a test now block any commit that contains a key. Run logs are no longer tracked. (000) A small evaluation on the live Groq models: attacks 32 of 33, 2 deals closed with 0 limit breaks (rubric 0.920 PASS). It found that Groq's per-minute limit made the Safety Guard fail closed in a burst; the model client now waits longer on a 429 (1, 2, 4, 8 seconds or the host's Retry-After, up to 15 s). (00) Email and Gmail were removed from the code, the website, the progress bar and the docs for now (parked in `DO_IT_LATER.md`, section 7); the Buy page vendors are chats only. (0) The bigger evaluation finished (8 deals per version, with the LLM judge): the real agent 0 limit breaks, 0 private items shared, 33 of 33 attacks, rubric 0.947 PASS; the baseline 7 limit breaks, 49 private items shared, rubric 0.407 FAIL. Stored and on the Scorecard. Also: the agent negotiates even with no trusted market price, patient small talk, kind replies, the research box in New chat, a broader second search, no demo data flicker, no preset chats, Inbox rules card removed. 1,433 backend tests pass. (1) The buyer box on the WhatsApp page now starts a NEW chat by itself: write what the buyer wants, it reads the item and the maximum and opens the chat at the top, where you play the vendor (`/demo/chat` accepts `scenario:"custom"`). (2) A good price no longer ends in silence: the agent asks the vendor to confirm the requirements (model, brand new and sealed, warranty, delivery time), then thanks them once. It is never an acceptance. (3) Casual talk and patience: small talk gets a friendly human reply with no price pressure; if the vendor keeps chatting, the agent sends two messages at once, the reply and then a way back to the price (the market price, "too high" only when true, a real competing price as a number only, and "I came to you because I think you can give me a better price than that seller"). (4) Up to 10 rounds (`MAX_ROUNDS`) and 300 model calls per deal. 1,403 backend tests pass. Deployed (backend on FastAPI Cloud, website on Vercel). Before that (3 Oct 2026): the agent keeps talking, the price check before the maximum, the evaluation (0.950 PASS against the baseline 0.450 FAIL), the README. Before that: Phase 5 (the evaluation framework and the Scorecard) is built. The backend is deployed to FastAPI Cloud on Groq and the website on Vercel; the live flow was tested end to end. Before that: the agent now tracks the tokens of every model call (Ollama included), `AGENT_EXECUTION_FLOW.md` documents how the agents run, and the first token optimizations are built (1,304 backend tests pass). Before that: the Assistant chat, chats that never close, variants and free extras, the final pick and the Closer, `/trick`, and local Ollama versus deployed Groq (`APP_ENV`).
**Just verified:** a full Buy flow run on the real local stack (Supabase, Ollama, the backend) through the API, 3.5 minutes. It found one bug (the first message was sent twice), now fixed with regression tests. Clicking through the website in a browser is still to do by hand.
**Also fixed from your live test:** the Buy page now has two buttons (Chat or Form), vendors default to "I play it" (the agent sends only the first message, then waits for you), a failed research no longer stops the first message, the research no longer fails on variants, and a "Search again" button was added.
**Next step:** you test the WhatsApp page and Start purchase (small talk, the "I will check the market" line, the replies after the Accept box). Then test in a fresh browser and on a phone. Decided 4 Oct 2026: the Reset button stays on for reviewers, and the pasted keys are not rotated. Email was removed for now (see `DO_IT_LATER.md`, section 7). Parked work is in `DO_IT_LATER.md`.

## Overview

| Phase | What | Status |
|---|---|---|
| 0 | Setup: tools, repo, accounts | Done (rotate the pasted keys at the end) |
| 1a | Frontend with mock data | Done |
| 1b | Pipeline: backend, database, first deploy | Done |
| 2 | Backend core: schemas, Limit Checker, Safety Guard, Fact Checker, simulator, budgets, resume | Done |
| 3 | Agents and research: Researcher, strategy, Negotiator, Manager (LangGraph), Closer, Assistant, `/trick` | Done, except `/parse-request` |
| 4 | Connect the real frontend | Done. You tested the full flow on the live site many times and the problems you found were fixed the same day (latest, 4 Oct 2026: New chat box with real price research and vendor picker, replies after the Accept box, no demo-data flicker, no preset chats). Left: your phone and fresh-browser check. |
| 5 | Evaluation and scorecard | Built and run (4 Oct 2026, 8 deals per version, with an LLM judge for chat tone): baseline rubric 0.407 FAIL (7 limit breaks, 49 private items shared, 2 of 33 attacks), the real agent rubric 0.947 PASS (0 limit breaks, 0 private items shared, 33 of 33 attacks, judge 0.67). Stored and on the Scorecard. Left: a stronger judge model and trace evaluation (see DO_IT_LATER.md). |
| 6 | Hardening, README, security check | Done (3 to 4 Oct 2026): README with the architecture diagram, "waking up" and loading messages, a saved real run for `/demo/recorded`, and the security check (no secrets in git history, env files untracked, CORS only for the website, rate limit tested live: the 31st write in a minute gets 429, daily budgets). Also an error page with Try again, a not-found page, a loading screen, and a Scorecard retry. |
| 7 | Hosted model and final deploy | Deployed (3 Oct 2026): backend https://dealdesk.fastapicloud.dev on Groq, website https://dealdesk-xi.vercel.app. Left: your phone and fresh-browser test, and rotating the keys. |
| 8 | Real Gmail | Removed for now (4 Oct 2026). Parked in `DO_IT_LATER.md`, section 7, with how to bring it back. |

## What is built (by phase)

### Phase 0 to 2 (foundation)
- Tools, repo, env files, GitHub, Vercel and FastAPI Cloud deploys, Supabase.
- Frontend on demo data: login, Home, Buy form with CSV and Excel upload, deals page in a WhatsApp Web style, WhatsApp demonstration, Scorecard page (shows "No run yet", never fake numbers).
- Backend core: Limit Checker (plain code, no AI), Safety Guard (48 rules plus the model), Fact Checker (27 rules, sentence filter, per-claim model verdicts, rewrite loop), Simulator (5 personas, 30 attacks), budget, rate limit, leases and restart recovery.

### Phase 3 (agents and research)
- Researcher: search, verified price reading, currency, price math, 24 hour cache, credit counter.
- Strategy (counter formula, decisions), tactics playbook, Negotiator (first message is a fixed template), Offer Reader, Firm Price check, Best Offer Tracker (leverage line without names, hold rule, wake-ups).
- Variants (color, size) and free extras with the effective price.
- The Manager: a LangGraph graph per vendor message, saved to Supabase after every node, many vendors in parallel.
- Closer and decisions: accept, counter, reject, stop and choose, reject all. Only you can accept.
- Assistant chat that never closes: a new purchase request starts a new product, only after a clear yes.
- `/trick` ("Try to trick it") on a throwaway copy of the deal.
- Token tracking for every model call, `AGENT_EXECUTION_FLOW.md`, and the first optimizations.
- `/parse-request` reads one sentence into form fields (the model reads the words, the price parser finds the maximum price, nothing starts).

### Phase 4 (real frontend)
- The website uses the real API. Demo data only when the backend cannot be reached.
- Choose which vendors you play (any subset), the Best Deal and final pick card, the assistant chat on the Buy page, variant and extras fields, "Agent off" and model status in the top bar, long waits for the model (3 minutes) instead of 5 seconds.
- Verified: a full flow run on the real local stack through the API. The buyer box on the WhatsApp page is built. Left: a browser click-through.

### Phase 7 (partly)
- `APP_ENV=local` uses Ollama and never touches Groq. `APP_ENV=production` switches to Groq by itself and refuses to start without a Groq key.
- The Groq key does not list the Llama models first planned. The defaults are now `openai/gpt-oss-120b` (main) and `openai/gpt-oss-20b` (fast and fallback), chosen from the key's list and smoke tested (about 0.6 seconds a call, against 10 to 60 seconds on the laptop model).

## Notes

- Run everything locally: `cd backend && uv run fastapi dev --port 8000` and `cd frontend && npm run dev -- -p 4000`. Port 3000 is used by other projects on this machine. For a rehearsal without Supabase or a model: `uv run python scripts/dev_server_memory.py` (port 8001).
- Local `backend/.env` for play: `APP_ENV=local`, `AGENT_ENABLED=true`, `RESEARCH_MODE=fixed` (a demo market price, no Tavily credits). Set `RESEARCH_MODE=web` for real research.
- The SQL files in `backend/sql/` (001, 002, 003, 004) are all installed in Supabase. `004_agent_state.sql` is safe to run again.
- A local model call takes 10 to 60 seconds on this machine, and a message with a counter takes a few of them. That is the cost of free and unlimited. Groq will be faster.
- Token data: `backend/data/llm_usage*.jsonl` (counts only). The baseline is `llm_usage_before.jsonl` (27 calls, 17,082 tokens). Keep it for the before and after comparison.
- **Rotate the keys pasted in chat (Supabase, OpenRouter, Groq, Tavily) now: they are on a live server.** After rotating, update the three secrets on FastAPI Cloud (`uv run fastapi cloud env set NAME --value-stdin --secret`) and `backend/.env`. Check the Tavily dashboard that pay-as-you-go is OFF.
- Frontend pages show a "Demo data" banner whenever they use mock data. The mock backend is `frontend/src/lib/mock.ts`.
- Next.js 16 renamed `middleware` to `proxy`. Pages are protected with `requireSession()` (CLAUDE.md section 4). `frontend/AGENTS.md` and `frontend/CLAUDE.md` come from Next.js.
- Vercel: the project Root Directory is `frontend`. Deploys also work from the CLI (`cd frontend && vercel deploy --prod`).
- Backend deploy: `cd backend && uv run fastapi cloud deploy`. It is live and current (3 Oct 2026) at https://dealdesk.fastapicloud.dev with these variables set on FastAPI Cloud: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (secret), `GROQ_API_KEY` (secret), `TAVILY_API_KEY` (secret), `APP_ENV=production`, `AGENT_ENABLED=true`, `RESEARCH_MODE=web`, `ALLOWED_ORIGINS`, and the testing switch `ALLOW_RESET=true` (turn it off when testing is over, see docs/setup.md). The website's `NEXT_PUBLIC_API_URL` points to it, and Vercel deploys on every push.
- The safety numbers (Safety Guard 0 dangerous errors on 28 messages, Fact Checker 0 of 13 honest wrongly blocked and 0 of 12 lies passed) are small samples on `llama3.1:8b`, and some attacks resembled ones used while tuning. Phase 5 must use fresh attacks.
- A fully LLM-played vendor is still planned (a sixth persona).
