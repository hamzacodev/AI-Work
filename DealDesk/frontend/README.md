# DealDesk frontend

The website for DealDesk, an AI agent that negotiates with vendors for you, within limits that plain code enforces.
Next.js 16 (App Router), React 19, Tailwind CSS v4, TypeScript.

The project guide is [CLAUDE.md](../CLAUDE.md). How the agents run is in [AGENT_EXECUTION_FLOW.md](../AGENT_EXECUTION_FLOW.md).
Design rules and pages are in [docs/frontend.md](../docs/frontend.md).

## Run it

```bash
cd frontend
npm install
npm run dev -- -p 4000        # open http://localhost:4000 (port 3000 is used by other projects on this machine)
```

Log in with the demo account from `.env.example` (`demo@dealdesk.app` / `Demo1234`).

The website talks to the backend at `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8000`):

```bash
cd backend
uv run fastapi dev --port 8000    # needs backend/.env, with AGENT_ENABLED=true to run the agent
```

Without a reachable backend the pages use demo data and show a "Demo data" banner. To try everything without Supabase or a model,
run `uv run python scripts/dev_server_memory.py` in `backend/` (port 8001) and start the website with
`NEXT_PUBLIC_API_URL=http://127.0.0.1:8001 npm run dev -- -p 4000`.

## Checks

```bash
npm run lint
npx tsc --noEmit
npm run build
```

## What is in it

- **Buy**: a chat with DealDesk (one chat that never closes, a new purchase request starts a new deal after a clear yes), the form
  with the variant and the free extras you value, a vendor table with CSV and Excel upload, and an "I play it" choice per vendor.
- **Deals**: the vendor chats (WhatsApp Web style), the Best Deal card and the final pick (Accept, choose another, reject all), who plays
  which vendor, the agent activity timeline, "Try to trick it".
- **WhatsApp demonstration**: you play the vendor and the buyer's agent answers.
- **Scorecard**: shows "No run yet" until real evaluation runs exist. It never shows invented numbers.
- **Planned** pages explain the roadmap. Nothing on them works yet.

## Deploy

Vercel, with the project Root Directory set to `frontend`. Production variables: `DEMO_EMAIL`, `DEMO_PASSWORD`, `SESSION_SECRET`,
`NEXT_PUBLIC_API_URL`. Deploy from the CLI with `vercel deploy --prod`. The live backend is still the old version until it is redeployed.
