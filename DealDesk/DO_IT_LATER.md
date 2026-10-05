# Do it later

Things we discussed and parked. Nothing here is built yet unless it says so. When we start one, move it to PROGRESS.md and
delete it from here.

Written from the audit of the current system (2 October 2026) and from the list of capabilities you asked for.

---

## 0. Found while deploying (3 Oct 2026)

- [x] Fixed 3 Oct 2026: a failed research no longer stops the first message, the research searches for the model (not the color or storage), and a "Search again" button exists. (Found by your live test with an Infinix phone.)
- [x] Partly fixed 4 Oct 2026: a wide range is flagged low confidence and the agent then negotiates from the vendors' own prices; prices that split into groups keep the biggest group; a broader second search runs when nothing matches every spec. Still open: asking you to confirm the exact model. Old note: **Research can be wrong for ambiguous items.** The live test for "Dell XPS 15 (black) 16GB RAM" returned a market range of $999 to $1,585 (mixed laptop generations) against a maximum of $800. The tracker then treated a real $720 offer as "not credible" (under half the market) and picked a $2,018 fake vendor as the best. The code behaved as designed, but the research input was poor. Options to decide: ask you to confirm the exact model, show the research sources and ask for a confirmation before negotiating, or warn when the market median is far above your maximum.
- [x] Checked 3 Oct 2026: the rate limit works on the live host (the 31st write in a minute got 429, it resets after a minute) and the server sees each visitor's real address, so it is per visitor. Old note: **Rate limit behind FastAPI Cloud was untested.** The limiter keys on `cf-connecting-ip`, else the connection address. If the host does not send a per-visitor address, all visitors may share one limit. The daily budgets are the real cost guard. Check the header the host sends, and set `CLIENT_IP_HEADER`.
- [ ] Test the live website in a fresh browser and on your phone (you).
- [x] Decided 4 Oct 2026: not rotating the keys that were pasted in chat (demo project). Rotate them if the chat transcript is ever shared. A secret scan found none in git, its history, the website build or the live API. They are now set on the live server as well.
- [x] Evaluation run 3 Oct 2026: baseline 5 deals (rubric 0.450 FAIL), the real agent 3 deals (0.950 PASS, 0 limit breaks, 0 private items shared, 0 invented facts, 33 of 33 attacks). Both stored. Still open: more deals (the 2 hour limit allows about 3 per run on the local model), the routing score 0.667 (the scenarios allow 3 rounds, the product 10: align `evals/scenarios.py`), and an evaluation sample on Groq.
- [x] Decided 4 Oct 2026: `ALLOW_RESET` stays on for the live demo so reviewers can test and reset (it only deletes deals and chats; the Scorecard is kept).
- [ ] Judge scores show the weak spots: patience with small talk (0.55) and variety (0.57). Tune with real transcripts.
- [ ] Conversation quality: the buyer messages are better (less repeated lines, chat replies, goodbye) but still template-shaped. Tune with real transcripts, keep the number checks as they are.
- [x] Safety Guard and Fact Checker re-checked on the Groq models (3 Oct 2026): Fact Checker 24 of 24 with no lie approved; Safety Guard normal 10/10, obvious 8/8, sneaky 8/10 (one obfuscated link, now a rule). A small Groq sample was run on 4 Oct 2026 (see docs/evaluation.md); a bigger one is still open.
- [ ] Re-check the new rules with a real run: the near-market-low stop (5 percent of the lowest price), the goodbye, and wake-ups of vendors who said no. The thresholds are guesses until measured.
- [ ] Vendor names in leverage: you asked once for names, we kept number only (your earlier decision). Decide yes or no.

## 1. Evaluation framework (evals)

Built on 3 Oct 2026 (`backend/app/evals/`, see `docs/evaluation.md`): a fixed dataset of scenarios, the product mode and an unprotected baseline mode, a runner, metrics, the weighted rubric with a pass threshold and hard failures, the attack suite, stored results and the Scorecard. The items below that are still open are what is not built.

Today there is no evaluation framework. What exists: 1,298 automated tests with fake models, a library of 30 attack messages with
expected verdicts, and by-hand check scripts for the Safety Guard, Fact Checker and Offer Reader. The `eval_runs` table is in the
database but unused, and the Scorecard page shows "No run yet".

To do:

- [x] A fixed scenario set (built). Still open: a dataset in one common format with expected agents, expected route and expected output per case
- [x] A runner for the whole pipeline (built). Still open: per-agent runs against expected output
- [ ] Evaluate the execution trace: which agents ran, in which order, which tools were called, routing and agent selection, retries and fallbacks
- [x] Task success: closed deals, limit breaks, private items shared, tricks handled (built)
- [x] Runs are repeatable (fixed seed) and stored (`eval_runs` and results JSON). Still open: comparing two runs automatically to flag regressions
- [x] `/scorecard` and the Scorecard page show only stored runs (built)
- [x] Safety on and safety off comparison (built)

## 2. Evaluation rubric and scoring

Today there is no rubric, no weights, no scoring and no thresholds.

To do:

- [x] Criteria, weights, scoring rules, pass threshold and hard failures are built (`evals/rubric.py`). The weights:

| Criterion | Weight |
|---|---:|
| Accuracy | 30% |
| Output quality | 20% |
| Tool usage | 15% |
| Decision and routing | 15% |
| Instruction following | 10% |
| Efficiency | 10% |

- [x] Each criterion is scored per run, with an overall score and a pass or fail (built). Still open: a score per agent, shown in a table
- [x] Pass and fail thresholds (built)
- [x] Evaluation reports: JSON with the transcripts, and the Scorecard page (built)
- [ ] An agent-level table: correctness, accuracy, output quality, instruction following, tool selection, tool-call correctness, routing correctness, expected versus actual, token efficiency, latency, failure handling

## 3. LLM as a judge

Today: NO. (The Safety Guard and Fact Checker use the model, but they are guards inside the product, not an evaluation judge.)

To do:

- [x] Built 4 Oct 2026 (`evals/judge.py`): the local model grades chat tone 1 to 5, stored in `detail.judge`. Open: a stronger judge model (the local one is lenient)
- [ ] Choose a stronger judge model and compare it with the local one
- [ ] Track the judge's inputs and outputs, token use and cost, and store its results

## 4. Execution trace and tracking

Today: a per-vendor timeline of what each agent did, and a log of every model call. No step timings, no parallel tracking, no record of tool calls, no complete trace.

To do:

- [ ] A complete end-to-end trace: each step with start, end, parent, input and output, linked to the vendor and the turn
- [ ] Record which steps ran in parallel, and what each agent was doing while another ran
- [ ] Record tool calls per agent (each Tavily and exchange-rate call)
- [ ] Record retries and fallbacks, including rate-limit waits and failed model calls
- [ ] Separate the waiting time for a free model slot from the model's own time

## 5. Token tracking and optimization (partly built)

Built: every model call is recorded (agent, purpose, model, provider, input, output, total, cached if reported, estimated split, list-price cost, latency, local or cloud). Local Ollama calls are included.
The optimizations are built and tested: compact JSON shape, shorter chat history, the Limit Checker result passed to the Fact Checker, parallel reads, research next to the safety check.

Open:

- [ ] Run the measurement again on the optimized code (`scripts/measure_tokens.py --label after --with-research`). The baseline is already measured: 27 calls, 17,082 tokens.
- [ ] Re-check the Safety Guard and Fact Checker accuracy with the real model (`check_safety.py`, `check_facts.py`), so the savings are shown not to lower quality
- [ ] Generate `docs/TOKEN_USAGE.md` with `scripts/token_report.py`, with the before and after table (input, output, total, number of calls, estimated cost)
- [ ] Detect repeated context, oversized prompts, duplicate calls and unnecessary calls automatically
- [ ] Find calls that could be code, a smaller model, cached or parallel, and show the expected effect of each
- [ ] Shorten the Safety Guard prompt (about 420 of its 528 input tokens are fixed instructions), after the 30 attack messages are re-checked with the real model
- [ ] Store the usage records in the database too, with a link to the vendor and the turn
- [ ] Measure the cached tokens when the provider reports them (Groq may)

## 5b. Groq model names (found 3 Oct 2026)

- [x] Done 3 Oct 2026: the defaults are `openai/gpt-oss-120b` and `openai/gpt-oss-20b` (the key does not list the Llama models), smoke tested.
- [ ] Still to do: re-measure the tokens and re-check the Safety Guard and Fact Checker on the Groq models (the safety numbers so far are only for `llama3.1:8b`), and run a small evaluation sample on Groq.

## 5c. Learning guide catch-up (you asked to do the learning later)

- [ ] `docs/LEARNING.md` is current up to section 7.27 (token tracking and the first real run). Still to add: the `/parse-request` chapter and the buyer box on the WhatsApp page, then the next steps. The execution flow, progress and architecture documents are kept current every step.

## 6. Keeping the documents true (built, keep doing)

- `AGENT_EXECUTION_FLOW.md` is the source of truth for how the agents run. Update it in the same step as any pipeline change. `tests/test_docs_in_sync.py` guards part of it.
- `docs/TOKEN_USAGE.md` is generated from real measurements. Rebuild it after every change that adds or reshapes a model call.

---

Everything else that is still open (the real model on Groq, the live deploy, rotating the keys, `/parse-request`) is tracked in PROGRESS.md.

---

## 7. Email (removed on 4 Oct 2026, parked)

The learner chose to leave email out for now. It was built, tested with a fake Gmail (10 tests) and switched off by default, but never run against a real Gmail account. It was removed from the code, the website, the progress bar and the docs so that nothing claims it works.

How to bring it back later:

- The code is in the git history. The commit that added it is `fd424c2` ("phase8: Gmail channel on your own account (off by default), tests with a fake Gmail, Check my email button"). Restore the files from there: `backend/app/channels/gmail.py`, `backend/tests/test_gmail_channel.py`, `backend/scripts/gmail_authorize.py`, and the pieces in `agents/runtime.py` (`channel`, `_send_email`, `poll_email`), `agents/wiring.py` (`build_email_channel`), `api/deals.py` (the poll route), `api/health.py` (`email_enabled`), `core/config.py` (`gmail_*`), `.env.example`, and in the frontend `lib/api.ts` (`pollEmail`) and `DealView.tsx` (the "Check my email" button).
- The one-time steps are yours, in the browser: Google Cloud project, Gmail API on, OAuth consent screen in Testing mode, a client id and secret, then run `scripts/gmail_authorize.py` for the refresh token. The test token expires every 7 days. Minimum scopes: send and read.
- Safety rules to keep (CLAUDE.md rules 8 and 9): send only to addresses in `OWNER_TEST_ALLOWLIST`, read only from them, and keep `REAL_SEND_ENABLED=false` by default. `REAL_SEND_ENABLED` and `OWNER_TEST_ALLOWLIST` still exist in the settings for this reason, and nothing uses them now.
- Decide approve-and-edit mode (the user approves each outgoing email) before any real sending.
- Then: one real round trip to your own address. It was worth 3.4 percent of the old progress bar.
- The Buy page vendor channel dropdown (email or chat) was also reduced to chat only, and a vendor file that says "email" is read as a chat. Bring the email option back with the rest.

