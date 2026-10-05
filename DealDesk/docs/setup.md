# DealDesk setup and deployment guide

Read this only in Phase 0 and when deploying or switching to Groq. The rules are in CLAUDE.md.

## Part 1: Setup and install (Phase 0)

Claude Code runs these with the learner, one at a time, and explains each. The learner's OS may be Windows, macOS or Linux. Ask once which one, then use the right commands. On Windows, use PowerShell (or WSL).

### Step A: check what is installed
```
node -v        # need 20 or newer (22 LTS is best)
npm -v
git --version
python --version   # any is fine, uv will manage Python 3.12
uv --version
ollama --version
```
Install only what is missing.

### Step B: install the missing tools
- **Node.js LTS:** from nodejs.org (or nvm).
- **Git:** from git-scm.com.
- **uv (Python package manager, installs Python 3.12 for us):**
  - macOS or Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`
  - Windows PowerShell: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`
  - Then restart the terminal and run `uv --version`.
- **Ollama:** download from ollama.com, install, then:
  ```
  ollama pull llama3.1:8b
  ollama run llama3.1:8b "Say hello in 5 words"
  ```
  Ollama listens on `http://localhost:11434`. Check the OpenAI-compatible endpoint:
  ```
  curl http://localhost:11434/v1/models
  ```
- Optional: VS Code with the Python, Ruff and Tailwind CSS IntelliSense extensions.

### Step C: create the project
```
mkdir dealdesk && cd dealdesk
git init
# copy CLAUDE.md into this folder
```
Create `.gitignore` in the root:
```
# node
node_modules/
.next/
.vercel/
# python
.venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
# secrets (keep the examples)
.env
.env.*
!.env.example
# os
.DS_Store
Thumbs.db
```

### Step D: frontend
```
npx create-next-app@latest frontend --typescript --tailwind --eslint --app --src-dir --import-alias "@/*" --use-npm
cd frontend
npm install read-excel-file papaparse
npm install -D @types/papaparse
npm run dev        # open http://localhost:3000
```
Then create `frontend/.env.local` from `.env.example`. Confirm Tailwind v4: `globals.css` starts with `@import "tailwindcss";` and there is no `tailwind.config.js`.

### Step E: backend
```
cd ..
mkdir backend && cd backend
uv init --python 3.12
uv add "fastapi[standard]" pydantic-settings httpx openai langgraph tavily-python supabase python-multipart
uv add --dev pytest pytest-asyncio ruff
```
- If `uv init` creates a `.git` folder inside `backend/`, delete it. The repo root is the only git repo.
- Make sure `.python-version` says `3.12` and `pyproject.toml` has `requires-python = ">=3.12,<3.13"`.
- Replace the generated `main.py` with a tiny FastAPI app that exposes `app` and has `GET /health`.
- Create the folders from section 5 of CLAUDE.md (`app/api`, `app/core`, and so on) with empty `__init__.py` files as each is needed, not all at once.
- Run it:
  ```
  uv run fastapi dev        # open http://127.0.0.1:8000/docs
  uv run pytest -q
  ```
- Create `backend/.env` from `.env.example`. The settings loader (`app/core/config.py`) reads it with `pydantic-settings`.

### Step F: accounts and keys (the learner does these in the browser)
1. **GitHub:** create an empty repo called `dealdesk`, then `git remote add origin <url>`.
2. **Supabase:** New project, save the Project URL and the `service_role` key into `backend/.env` only. In the SQL editor, run `backend/sql/001_schema.sql` when it exists (Phase 1b).
3. **Tavily:** sign up, copy the API key into `backend/.env`.
4. **Groq:** sign up, create an API key, save it somewhere safe. Do NOT enable it yet.
5. **Vercel:** sign in with GitHub. Create the project in Phase 1b with Root Directory `frontend`.
6. **FastAPI Cloud:** sign up, then run `uv run fastapi login` in `backend/` when it is time to deploy.

### Step G: first commit
```
cd ..
git add -A
git commit -m "phase0: project setup"
git branch -M main
git remote add origin https://github.com/<user>/dealdesk.git
git push -u origin main
```
Check that `.env` files are NOT in the commit: `git ls-files | grep env` must show only `.env.example` files.

### Phase 0 is done when
- `npm run dev` shows the Next.js starter page.
- `uv run fastapi dev` shows `/docs` and `/health` returns ok.
- `ollama run llama3.1:8b` answers.
- The repo is on GitHub with no secrets.
Then write `PROGRESS.md`, tick Phase 0, and give the NEXT STEP.

---


---

## Part 2: Deployment (free)

**Order:** local first, then deploy early (Phase 1b) to find hosting problems, then redeploy after each phase.

### Supabase
- Create a free project, paste `backend/sql/001_schema.sql` in the SQL editor, save URL and service role key in `backend/.env`.
- Free projects pause after 7 days of inactivity. Open the project and resume it before demos and before sharing the link.

### Backend on FastAPI Cloud
- From `backend/`: `uv run fastapi dev` for local, `fastapi deploy` to deploy. Set environment variables in the FastAPI Cloud dashboard.
- Known pitfalls to check before the first deploy: Python version mismatch (pin 3.12 in `.python-version` and `pyproject.toml`), missing dependency declaration, platform-specific wheels (for example `onnxruntime`, avoid heavy ML packages), the app entry point not found (keep `backend/main.py` exposing `app`), and missing environment variables on the server.
- The free hosting may sleep when idle. The frontend must show a "Waking up the server" message and retry on the first request.
- After deploy, set `ALLOWED_ORIGINS` to the Vercel URL.

### Frontend on Vercel
- Import the GitHub repo, set **Root Directory** to `frontend`.
- Environment variables: `DEMO_EMAIL`, `DEMO_PASSWORD`, `NEXT_PUBLIC_API_URL` (the FastAPI Cloud URL).

### Local first, Groq only when deployed (APP_ENV)

Locally the backend runs on Ollama (free, no limits) and never touches Groq, even though `GROQ_API_KEY` is in `backend/.env`.
On the deployed server set `APP_ENV=production` and `GROQ_API_KEY`: the code switches the model settings to Groq by itself. With
`APP_ENV=production` and no Groq key the server refuses to start. For playing around locally you can also set `RESEARCH_MODE=fixed`
so the market price is a demo price and no Tavily credits are used, and `AGENT_ENABLED=true` so the agent runs on your machine.

### Switching Ollama to Groq (Phase 7)
- Change only the `LLM_*` variables on the server (see section 6 of CLAUDE.md). No code change.
- Run a short smoke test first: one full deal, then the attacker persona, then check that JSON output still validates.
- Planned Groq defaults: `llama-3.1-8b-instant` for fast agents, `llama-3.3-70b-versatile` for the Negotiator with fallback to the 8B model on rate limit.
- **Done (3 Oct 2026):** the Groq key in this project does not list those two Llama models. The defaults are now `openai/gpt-oss-120b` (main) and `openai/gpt-oss-20b` (fast and fallback), chosen from the key's own list and smoke tested. List what a key can use with `GET https://api.groq.com/openai/v1/models`, and override with `GROQ_MODEL_MAIN`, `GROQ_MODEL_FAST`, `GROQ_MODEL_FALLBACK`.

---



## Testing switch: ALLOW_RESET (3 Oct 2026)

`ALLOW_RESET=true` lets the website button "Reset all (test)" delete every deal, vendor chat and assistant chat (`POST /admin/reset`). It is `false` by default. Decided 4 Oct 2026: it stays `true` on the live demo so reviewers can test and reset. It only deletes deals and chats: the Scorecard results, the research cache and the usage counters are kept, and the rate limit still applies. Turn it off (below) if the demo holds anything that matters. Local `backend/.env` has it on. Turn it off on FastAPI Cloud with `printf false | uv run fastapi cloud env set ALLOW_RESET --value-stdin` and then `uv run fastapi deploy`. Defaults changed the same day: `MAX_ROUNDS=6`, `MAX_LLM_CALLS_PER_DEAL=200`.


## Email

Email was removed from the project for now. See `DO_IT_LATER.md`, section 7, for how to bring it back.
