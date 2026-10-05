// API client. Calls the backend and falls back to mock data when the backend
// is unreachable or the endpoint does not exist yet (CLAUDE.md section 9).
// Phase 4 removes the fallback.

import {
  mockCreateDeal,
  mockDecision,
  mockGetDeal,
  mockParse,
  mockRecorded,
  mockSetControl,
  mockTrick,
  mockVendorMessage,
} from "./mock";
import type {
  MarketPrice,
  ActionResult,
  AssistantChat,
  CreateDealInput,
  CreateDealResponse,
  Deal,
  DecisionBody,
  DecisionResult,
  FinishAction,
  ParsedRequest,
  PlayedBy,
  Result,
  Scorecard,
  TrickResult,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

type Raw = { status: number | null; body: unknown };

// A request waits this long by default. Anything that asks the language model (the assistant, "try to trick it") waits much
// longer, because a model on a laptop can take a minute. Before, every request gave up after 5 seconds, which looked like
// "the backend is not reachable" even though it was only thinking.
const QUICK_MS = 15_000;
const MODEL_MS = 180_000;

async function raw(path: string, init?: RequestInit, timeoutMs: number = QUICK_MS): Promise<Raw> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}${path}`, {
      ...init,
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    });
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      body = null;
    }
    return { status: res.status, body };
  } catch {
    return { status: null, body: null };
  } finally {
    clearTimeout(timer);
  }
}

/** True when the backend cannot serve this request, so the mock should answer. */
function unavailable(r: Raw): boolean {
  return r.status === null || r.status === 404 || r.status >= 500;
}

function post(path: string, data: unknown, timeoutMs: number = QUICK_MS): Promise<Raw> {
  return raw(path, { method: "POST", body: JSON.stringify(data) }, timeoutMs);
}

/** The server answered, but it is not running the agent (AGENT_ENABLED is off). A real problem to show, not a reason for demo data. */
function agentOff(r: Raw): boolean {
  return r.status === 503 && (r.body as { detail?: { error?: string } } | null)?.detail?.error === "agent_disabled";
}
const AGENT_OFF = "The agent is not running on this server. Set AGENT_ENABLED=true in backend/.env and restart the backend.";

export async function checkHealth(): Promise<{ connected: boolean; model?: string; provider?: string; agentEnabled?: boolean }> {
  const r = await raw("/health");
  if (r.status === 200 && r.body && typeof r.body === "object") {
    const b = r.body as { model?: string; provider?: string; agent_enabled?: boolean };
    return { connected: true, model: b.model, provider: b.provider, agentEnabled: b.agent_enabled };
  }
  return { connected: false };
}

export async function parseRequest(text: string): Promise<Result<ParsedRequest>> {
  const r = await post("/parse-request", { text }, MODEL_MS); // the real model reads the sentence, which can take a while on a laptop
  if (r.status === 200) return { data: r.body as ParsedRequest, source: "api" };
  return { data: mockParse(text), source: "mock" };
}

/** What the item costs, before you choose a maximum. Uses a few search credits unless the price was searched in the last 24 hours. */
export async function marketPrice(item: string, mustHaves: string[], currency: string): Promise<{ data: MarketPrice | null; error?: string }> {
  const r = await post("/market-price", { item, must_haves: mustHaves, currency }, MODEL_MS);
  if (r.status === 200) return { data: r.body as MarketPrice };
  if (agentOff(r)) return { data: null, error: AGENT_OFF };
  if (r.status === 429) return { data: null, error: "Demo limit reached, try tomorrow." };
  if (r.status === 422) return { data: null, error: "Write the item first." };
  return { data: null, error: "The price check needs the connected backend. Try again in a moment." };
}

export async function createDeal(input: CreateDealInput): Promise<Result<CreateDealResponse>> {
  const r = await post("/deals", input, 30_000);
  if (r.status === 200 || r.status === 201) {
    return { data: r.body as CreateDealResponse, source: "api" };
  }
  return { data: mockCreateDeal(input), source: "mock" };
}

/** A deal the backend does not know (404) is an error. Demo data is only shown when the backend cannot be reached. */
export async function getDeal(id: string): Promise<Result<Deal | null>> {
  const r = await raw(`/deals/${encodeURIComponent(id)}`);
  if (r.status === 200) return { data: r.body as Deal, source: "api" };
  if (r.status === 404) {
    // A deal made in demo mode only exists in this browser. Anything else is really not found.
    const demo = mockGetDeal(id);
    return demo.vendors.length > 0 && id.startsWith("demo-") ? { data: demo, source: "mock" } : { data: null, source: "api" };
  }
  // A real deal must never turn into demo data because one poll failed (a slow wake-up, a network blip, a 5xx): the caller keeps what it has.
  if (!id.startsWith("demo-")) return { data: null, source: "api", failed: true };
  return { data: mockGetDeal(id), source: "mock" };
}

export async function getRecorded(): Promise<Result<Deal>> {
  const r = await raw("/demo/recorded");
  if (r.status === 200) return { data: r.body as Deal, source: "api" };
  return { data: mockRecorded(), source: "mock" };
}

export async function sendDecision(
  dealId: string,
  body: DecisionBody,
): Promise<Result<DecisionResult>> {
  const r = await post(`/deals/${encodeURIComponent(dealId)}/decision`, body);
  if (r.status === 200) return { data: { status: "ok" }, source: "api" };
  if (r.status === 409) {
    const b = (r.body ?? {}) as { error?: string; message?: string };
    if (b.error === "over_limit" || b.error === undefined) {
      return { data: { status: "needs_confirmation", message: b.message ?? "This is above your limit. Continue anyway?" }, source: "api" };
    }
    return { data: { status: "error", message: b.message ?? "That decision cannot go ahead." }, source: "api" };
  }
  if (r.status === 429) return { data: { status: "budget_exhausted" }, source: "api" };
  if (agentOff(r) && !dealId.startsWith("demo-")) return { data: { status: "error", message: AGENT_OFF }, source: "api" };
  if ((r.status === 404 || r.status === 403 || r.status === 422) && !dealId.startsWith("demo-")) {
    const b = (r.body ?? {}) as { message?: string };
    return { data: { status: "error", message: b.message ?? "That decision cannot go ahead." }, source: "api" };
  }
  if (unavailable(r)) return { data: mockDecision(dealId, body), source: "mock" };
  return { data: { status: "error", message: "The request failed. Try again." }, source: "api" };
}

/** "stop_and_choose": stop texting vendors still negotiating, so you can choose now. "reject_all": no deal, nothing sent. */
export async function finishDeal(dealId: string, action: FinishAction): Promise<Result<ActionResult>> {
  const r = await post(`/deals/${encodeURIComponent(dealId)}/finish`, { action });
  if (r.status === 200) return { data: { status: "ok" }, source: "api" };
  if (agentOff(r)) return { data: { status: "error", message: AGENT_OFF }, source: "api" };
  if (r.status === 409 || r.status === 404) {
    const b = (r.body ?? {}) as { message?: string };
    return { data: { status: "error", message: b.message ?? "That is not possible now." }, source: "api" };
  }
  return { data: { status: "error", message: "This needs the connected backend. It is not available in demo mode." }, source: "mock" };
}

export async function resetEverything(): Promise<{ ok: boolean; message: string }> {
  const r = await post("/admin/reset", {}, MODEL_MS);
  if (r.status === 200) return { ok: true, message: "Everything was reset." };
  if (r.status === 403) return { ok: false, message: "Reset is switched off on this server. Set ALLOW_RESET=true on the backend." };
  return { ok: false, message: "The backend did not answer, nothing was reset." };
}

/** The WhatsApp demonstration: you play the vendor, the real agent answers on a throwaway deal. Nothing is stored or sent. */
export async function demoChat(
  scenario: string,
  history: { sender: "vendor" | "agent"; text: string }[],
  message: string,
  custom?: { item: string; max_price: number; currency: string; must_haves: string[] },
): Promise<Result<TrickResult | { budget_exhausted: true } | { error: string }>> {
  const r = await post("/demo/chat", { scenario, history: history.slice(-20), message, ...(custom ?? {}) }, MODEL_MS);
  if (r.status === 200) return { data: r.body as TrickResult, source: "api" };
  if (r.status === 429) return { data: { budget_exhausted: true }, source: "api" };
  if (agentOff(r)) return { data: { error: AGENT_OFF }, source: "api" };
  if (r.status === 422) return { data: { error: "Write a message of 1 to 500 characters." }, source: "api" };
  if (r.status !== null) return { data: { error: "The server could not answer this time. Try again in a moment." }, source: "api" };
  return { data: mockTrick(message), source: "mock" };
}

export async function trick(
  dealId: string,
  vendorId: string,
  message: string,
): Promise<Result<TrickResult | { budget_exhausted: true } | { error: string }>> {
  const r = await post("/trick", { deal_id: dealId, vendor_id: vendorId, message }, MODEL_MS);
  if (r.status === 200) return { data: r.body as TrickResult, source: "api" };
  if (r.status === 429) return { data: { budget_exhausted: true }, source: "api" };
  if (!dealId.startsWith("demo-")) {
    if (agentOff(r)) return { data: { error: AGENT_OFF }, source: "api" };
    if (r.status === 404) return { data: { error: "Deal or vendor not found." }, source: "api" };
    if (r.status === 422) return { data: { error: "Write a message to try." }, source: "api" };
    if (r.status === null) return { data: { error: "The backend did not answer. Is it running?" }, source: "api" };
  }
  return { data: mockTrick(message), source: "mock" };
}

/** Scorecard numbers come only from stored runs. There is no mock: no data means "No run yet". */
export async function getScorecard(): Promise<Result<Scorecard | null>> {
  const r = await raw("/scorecard");
  if (r.status === 200) return { data: r.body as Scorecard, source: "api" };
  return { data: null, source: "mock" };
}

/** Take control of one vendor, or hand it back to the simulator. */
export async function setControl(dealId: string, vendorId: string, mode: PlayedBy): Promise<Result<ActionResult>> {
  const r = await post(`/deals/${encodeURIComponent(dealId)}/vendors/${encodeURIComponent(vendorId)}/control`, { played_by: mode });
  if (r.status === 200) return { data: { status: "ok" }, source: "api" };
  if (r.status === 422) return { data: { status: "error", message: "That option is not available." }, source: "api" };
  if (agentOff(r) && !dealId.startsWith("demo-")) return { data: { status: "error", message: AGENT_OFF }, source: "api" };
  if (r.status === 404 && !dealId.startsWith("demo-")) return { data: { status: "error", message: "Vendor not found." }, source: "api" };
  return { data: mockSetControl(dealId, vendorId, mode), source: "mock" };
}

/** Take control of (or hand back) the vendors you choose, all in one call. Vendors you do not list stay as they are. */
export async function setControlMany(dealId: string, vendorIds: string[], mode: PlayedBy): Promise<Result<ActionResult>> {
  if (mode === "llm") return { data: { status: "error", message: "The LLM vendor is planned and not available yet." }, source: "api" };
  const r = await post(`/deals/${encodeURIComponent(dealId)}/control`, { vendor_ids: vendorIds, played_by: mode });
  if (r.status === 200) return { data: { status: "ok" }, source: "api" };
  if (agentOff(r) && !dealId.startsWith("demo-")) return { data: { status: "error", message: AGENT_OFF }, source: "api" };
  if (r.status === 404 && !dealId.startsWith("demo-")) return { data: { status: "error", message: "A selected vendor was not found." }, source: "api" };
  if (r.status === 422) return { data: { status: "error", message: "That option is not available." }, source: "api" };
  for (const id of vendorIds) mockSetControl(dealId, id, mode); // demo mode: the backend is not reachable
  return { data: { status: "ok" }, source: "mock" };
}

/** The tester types a message as the vendor. The agent answers in the background, so the page polls for the reply. */
export async function sendVendorMessage(dealId: string, vendorId: string, text: string): Promise<Result<ActionResult>> {
  const r = await post(`/deals/${encodeURIComponent(dealId)}/vendors/${encodeURIComponent(vendorId)}/message`, { text });
  if (r.status === 200 || r.status === 202) return { data: { status: "ok" }, source: "api" };
  if (r.status === 429) return { data: { status: "budget_exhausted" }, source: "api" };
  if (r.status === 409) return { data: { status: "error", message: "Switch this vendor to You before typing as the vendor." }, source: "api" };
  if (agentOff(r) && !dealId.startsWith("demo-")) return { data: { status: "error", message: AGENT_OFF }, source: "api" };
  if (r.status === 404 && !dealId.startsWith("demo-")) return { data: { status: "error", message: "Vendor not found." }, source: "api" };
  return { data: mockVendorMessage(dealId, vendorId, text), source: "mock" };
}

/** The assistant chat. `null` when the backend cannot be reached (demo mode has no assistant). */
export async function getAssistant(): Promise<AssistantChat | null> {
  const r = await raw("/assistant");
  return r.status === 200 ? (r.body as AssistantChat) : null;
}

export async function sendAssistant(text: string): Promise<{ chat: AssistantChat | null; error?: string }> {
  const r = await post("/assistant/message", { text }, MODEL_MS);
  if (r.status === 200) return { chat: r.body as AssistantChat };
  if (r.status === 429) return { chat: null, error: "Demo limit reached, try tomorrow." };
  if (r.status === 422) return { chat: null, error: "Write a message of up to 500 characters." };
  return { chat: null, error: "The backend did not answer. Is it running? A model on a laptop can also take a minute, so wait a little and try again." };
}

/** Search the market price again after a failed research. It uses search credits. The agent then continues by itself. */
export async function retryResearch(dealId: string): Promise<ActionResult> {
  const r = await post(`/deals/${encodeURIComponent(dealId)}/research/retry`, {}, 30_000);
  if (r.status === 202 || r.status === 200) return { status: "ok" };
  const b = (r.body ?? {}) as { detail?: { message?: string; error?: string } };
  if (agentOff(r)) return { status: "error", message: AGENT_OFF };
  if (r.status === 409) return { status: "error", message: b.detail?.message ?? "This deal already has a market price." };
  return { status: "error", message: "Could not search again. Try later." };
}
