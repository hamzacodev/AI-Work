# DealDesk frontend guide

Read this in Phase 1a and whenever you change pages. The rules are in CLAUDE.md. The API contract is in section 8 of CLAUDE.md.

### Part 1: Design rules (follow exactly)
- Two themes, light and dark (a round button at the top right switches, the choice is remembered, the first visit follows the computer's setting). **Light text on dark backgrounds, dark text on light backgrounds.** All colors are tokens in `globals.css` (`:root` for light, `[data-theme="dark"]` for dark), so no component hard-codes a color. Every main text and chip pair was checked for readability (WCAG AA) in both themes.
- **Never hardcode `#000`, `#111` or any near-black as a text color.** Neutral text uses `var(--color-text-primary)` or `var(--color-text-secondary)`, defined in `globals.css`.
- Colored cards: text on a light colored fill uses the 800 or 900 shade of that color. Text on a dark colored fill uses the 50 or 100 shade.
- Blue accent on soft cool greys, dark pill buttons (a calm dashboard look, not WhatsApp green). Cards are `rounded-2xl` with a soft shadow. A sidebar card on a large screen and a top bar on a phone. Mobile friendly: check every page at 380px width.
- No emojis. Short plain copy. **No em dashes in any UI text, README or docs.**
- Do not use the banned phrases: "passionate about", "game changer", "revolutionizing", "unlock the power of", "in today's fast-paced world", "leverage cutting-edge". No buzzword stacking.
- Build with mock data first (`src/lib/mock.ts`). If the API is unreachable, fall back to mock data so every page still works.


### Part 1b: Pages
1. `/login`: demo login. Show the dummy email and password on the page. A server action checks `DEMO_EMAIL` and `DEMO_PASSWORD`, sets an httpOnly cookie. Every other page redirects to `/login` without the cookie, using a server-side `requireSession()` helper (not middleware).
2. `/home`: title "What do you want to do?" and the subtitle "One engine for every deal. Buy is live. The rest are on the roadmap." Three groups of cards, each with a chip, Live or Planned:
   - Money and business: Buy from vendors (Live), Sell, Get an investor, Review pitches, Freelance rates and client payments, Sponsors and partnerships.
   - Daily life: Rent a house, Rent out a house, Used items, Bills and services.
   - Work: Find a job and negotiate salary, Hire.
   Below the cards, a "How it works" strip with 4 steps: You say what you want. DealDesk contacts people and researches real prices. Your limits are enforced by code. You decide and DealDesk finishes the deal.
3. `/planned/[slug]`: one template for every Planned item with the sections: What it will do, Which side you can be, Rule enforced in code, Closing step, "Uses the same engine as Buy" (list of reused agents), and a chip "Planned, not built yet". Content for each slug is in part 3 below.
4. `/buy`: a chat box at the top ("I want to buy a Dell XPS 15 under $800 with 16GB RAM") that calls `POST /parse-request` and fills the form below. The user can edit every field.
   - Fields: item, maximum price, currency (USD, PKR, AED, GBP, EUR, SAR), must-have features, delivery address, phone (optional).
   - Vendor list, two ways: type rows in a table (name, contact, channel; add and remove rows), or upload an Excel/CSV file with preview and bad-row flags (see part 2 below).
   - Start button calls `POST /deals`. If the response says some vendors were skipped (the cap is `MAX_VENDORS_PER_DEAL`), show that message. Then go to `/deals/[id]`.
   - Pre-fill with: Dell XPS 15, max 800, USD, 16GB RAM, and 5 sample vendors.
5. `/deals/[id]`: dashboard. One row per vendor with a status badge. Poll every 3 seconds. Clicking a row opens a side panel with two tabs: **Conversation** (chat bubbles) and **Agent activity** (timeline, for example "Researcher found a fair price of $700 from 3 sources" with clickable source links, "Limit Checker blocked accepting $900"). A `needs_you` row shows a Decision card with Accept, Counter (price field) and Reject. Accept shows the Closer message. Include a "Try to trick it" box: the user types a message as the vendor and sees whether it was blocked and why. Show the research summary (low, median, high, number of sources, confidence). When a `needs_you` row has a `recommendation`, show it as advice with the reason. If the Accept price is above the maximum (or a Counter is above the ceiling), the API returns 409: show a confirm dialog ("This is above your limit. Accept anyway?" or "This counter will reveal your limit") and resend with `confirm_over_limit: true` only if the user confirms. If the API returns `budget_exhausted`, show a friendly message and a "View a recorded run" button that loads `GET /demo/recorded` (label it "Recorded run").
6. `/whatsapp`: a WhatsApp-style chat view of a vendor conversation (green and white bubbles, double ticks, timestamps, phone-shaped frame). Label at the top: **"WhatsApp demonstration"**. Smaller text: "The same agents also run on email." The user can type as the vendor (uses `POST /trick`). Do not claim real WhatsApp is connected.
7. `/scorecard`: two columns, Safety off and Safety on. Rows: deals closed percent, limit broken, private item shared, invented facts, tricks blocked percent, average savings percent, research accuracy percent. Show the model name, the judge model and judge note, the number of deals, the percentage of deals closed, and the run date. Load from `GET /scorecard`. If no run exists, show "No run yet".
8. Top nav: Home, Buy, WhatsApp, Scorecard, Log out.


### Part 2: Vendor list upload (Excel or CSV)
Parsing happens in the BROWSER. Backend only receives validated JSON.
- Accepted: `.xlsx` and `.csv`, max 1 MB, max 200 rows.
- Columns: `name`, `email` or `phone` (one contact column is fine), `channel` (optional, default `email`).
- The npm package `xlsx` is outdated on npm and has known vulnerabilities. Use `read-excel-file` for `.xlsx` and `papaparse` for `.csv`, or `exceljs`.
- Show a preview table before Start. Flag bad rows (missing name, missing contact, invalid email or phone, duplicate contact) and let the user fix or remove them.
- Offer a "Download sample file" link (a small CSV in `frontend/public/`).
- The backend validates again with Pydantic. Never trust the browser.

---


### Part 3: Content for the Planned pages
Each entry: what it will do, rule enforced in code, closing step.
- **Sell:** handles buyers who write to you. Rule: never go below your minimum, never hand over before payment is confirmed. Closing: confirms payment, shares pickup details. Sides: seller or buyer.
- **Get an investor:** researches investors, writes outreach, answers their questions. Rule: never invent numbers, never share the cap table. Closing: sends the deck and meeting slots. Sides: founder or investor.
- **Review pitches:** researches founders, replies with approved information only. Closing: asks for the deck, sends meeting slots. Side: investor.
- **Freelance rates and client payments:** negotiates rates, chases late invoices, offers payment plans. Rule: never below your minimum rate. Closing: confirms scope and payment plan.
- **Sponsors and partnerships:** handles brand offers. Rule: only the terms you approved. Closing: confirms the deal terms.
- **Rent a house:** researches local rents, negotiates, asks for pictures, a video and documents. Rule: no advance money before you have seen the place. Closing: books the visit, handles the agreement. Sides: tenant or landlord.
- **Rent out a house:** handles tenants. Rule: ask for ID and references before booking a visit. Closing: books the visit, sends the agreement after you approve.
- **Used items:** handles buyers and sellers on marketplaces. Rule: your minimum or maximum price. Closing: confirms price and handover.
- **Bills and services:** negotiates or cancels internet, insurance and subscriptions. Rule: never accept a longer contract than you approved. Closing: confirms the new price or the cancellation.
- **Find a job and negotiate salary:** contacts recruiters, researches market pay, negotiates salary and benefits. Rule: never below your minimum salary, share only what is in your CV. Closing: sends CV and availability, confirms the interview, negotiates the offer. Sides: candidate or employer.
- **Hire:** screens candidates and schedules interviews. Rule: screen only against your requirements. Closing: interview slots, offer only after you decide.
- **Inbox rules:** removed from the website on 4 Oct 2026 (it can come back later).

---


---

## Part 5: Additions after the first build

- **Chat with DealDesk** (`AssistantChat`, top of the Buy page): one chat that never closes. You write what you want to buy, a new purchase request starts a NEW draft, and a deal starts only after a clear yes. It needs the connected backend and says so in demo mode. No dead ends: nowhere says "conversation closed". A finished deal shows "Deal done", and the chat stays open.
- **Variant and extras fields** on the Buy form: the variant you want, other variants you would accept, and the free extras you value with your own estimate of their worth. Your estimates are labelled as estimates.
- **Who plays which vendor**: an "I play it" checkbox per vendor on the Buy form and a "Who plays which vendor?" panel on the deal page. Any subset of vendors can be played by you.
- **Best deal and final pick** card: ranks vendors on the effective price, shows why each stopped, and holds Accept, Choose a different vendor, Reject all, and Stop and choose now. Only you can accept.
- **Waiting for the model.** Requests wait 15 seconds by default. The assistant and "Try to trick it" wait 3 minutes, because a model on a laptop can take a minute. When the server is up but the agent is off (`AGENT_ENABLED` false), the website shows that message, and the top bar says "Agent off". The top bar also shows the model host (`ollama` or `groq`).
- **Buy page: two buttons, Chat or Form.** You choose how to start, and only that one is shown (the choice is remembered). Vendors default to "I play it": the agent sends the first message to each vendor, and then waits for you to type the vendor's replies. Untick a vendor to let a fake tester answer for it. On a deal whose market research failed, a "Search again" button (it uses search credits) searches again.
- **WhatsApp demonstration page**: you play the vendor against a buyer agent. There are no preset chats: you start each one with "New chat". It calls `POST /demo/chat`, which runs the real agent on a throwaway deal with a fixed demo market price. Nothing is stored or sent, and no real WhatsApp is connected. The page shows "typing..." while the agent works, has one-tap messages to try (a normal price, a refusal, small talk, and the tricks: ask for the maximum, ignore the rules, advance payment, address), a "Start over" button per chat, a red bubble when the agent blocks a message, and a small grey "Why" line under each reply. The "New chat" box (`NewChatBox`) sits under the chats: write what the buyer wants, press Understand, pick one or more dummy vendors (TechHub Store, Digital Bazar, Gadget World, Prime Electronics), and one chat opens per vendor. There is no maximum to type: the demo uses a dummy one ($1,000) unless the sentence has one. After Understand it also runs the real price research (`/market-price`, sources shown as links) and the demo agent uses that market price. It calls `/demo/chat` with `scenario:"custom"`. Two chats of the same buyer do not share prices: each demo chat is separate. Vendors are chats for now: the email option is removed from the Buy page.
- **The buyer request box** (under the chats on the WhatsApp page): a sentence is read into fields. If the sentence has no maximum price, you type it in the box (with a market price check next to it) instead of being stuck. With no saved vendors it starts with 3 sample vendors you play.
- **Check market price** (Buy form, under the item) and the chat assistant: shows the low, typical and high market price with source links and a realistic range for your maximum ("Use $X" buttons fill the field). A warning appears when your maximum is below the lowest price. It uses `POST /market-price` (a few search credits, cached 24 hours, the deal reuses the result).
- **Accept or Reject only at the end.** There is no decision box in a chat while any chat is still negotiating. When every chat is finished, the Best Deal box at the top shows the lowest price and the Accept button, and only the cheapest vendor's chat shows a decision box. A rejected vendor is labelled "Rejected by you", a passed-over one "Closed", and only the accepted one "Deal done".
- **Counter by hand**: every chat the agent stopped on has a small counter box, with a confirmation after you send it. It accepts what people type: "285", "285?", "$285", "1,285.50" (the first number is the price).
- **Lowest price mark**: after every chat is finished, the cheapest vendor is highlighted in the list with a green "Lowest price" tag. A vendor the agent stopped texting for a normal reason (a final price, a clear no, rounds used) shows "Paused", not "Needs you". "Needs you" is only for real problems.
- **A small gap above your maximum**: when every chat is finished and the lowest offer is above your maximum, the Best Deal box says by how much (in money and percent). Within 10 percent it says "if a few dollars do not matter, you can accept it, after a confirmation". The Accept button then reads "(above your maximum)", and the confirmation dialog protects you from a mistake. A hand counter above your maximum asks for a confirmation too; exactly your maximum is always refused.
- **Vendor list order**: newest message on top, in a fixed order (it no longer jumps on refresh).
- **Reset all (test)** in the top bar: wipes every deal and chat. It works only when the backend has `ALLOW_RESET=true`. Testing only.
- **Chats never close.** After a deal the chat shows "Deal done" and the box stays open. Messages are saved and checked, and the agent does not negotiate any more.

