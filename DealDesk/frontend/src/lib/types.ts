// Shapes follow the API contract in CLAUDE.md section 8.1.

export type Channel = "email" | "chat";
export type VendorStatus =
  | "sent"
  | "replied"
  | "negotiating"
  | "paused"
  | "needs_you"
  | "closed"
  | "blocked";

export type Currency = "USD" | "PKR" | "AED" | "GBP" | "EUR" | "SAR";
export const CURRENCIES: Currency[] = ["USD", "PKR", "AED", "GBP", "EUR", "SAR"];

export interface Message {
  from: "vendor" | "agent" | "owner";
  text: string;
  at: string;
  /** Written by a fake vendor (the simulator). Always marked, so nobody mistakes it for a real vendor. */
  simulated?: boolean;
}

export interface AgentEvent {
  agent: string;
  text: string;
  sources?: { title: string; url: string }[];
  at: string;
}

export interface Recommendation {
  action: "accept" | "reject" | "counter";
  reason: string;
}

/** Who answers for a vendor. "llm" is planned and not available yet. */
export type PlayedBy = "simulator" | "you" | "llm";

export interface Vendor {
  id: string;
  name: string;
  channel: Channel;
  status: VendorStatus;
  played_by?: PlayedBy;
  /** The fake vendor's personality (simulator only). */
  persona?: string | null;
  /** Why the agent stopped texting this vendor: firm_price, round_limit, good_price ... */
  stop_reason?: string | null;
  /** Prices the vendor gave for OTHER variants ("gray": 690). Information only. */
  variant_prices?: Record<string, number>;
  /** Free extras the vendor says it gives. `counted` is false when the vendor gives it only from a higher price. */
  addons?: { key: string; label: string; min_price: number | null; counted: boolean }[];
  /** The vendor said the price is final. */
  firm?: boolean;
  offer_price: number | null;
  recommendation?: Recommendation;
  messages: Message[];
  events: AgentEvent[];
}

export interface Research {
  low: number | null;
  median: number | null;
  high: number | null;
  n_sources: number;
  confidence: "low" | "medium" | "high";
  note: string;
  /** False when no usable market price was found. Then `reason` says why. */
  available?: boolean;
  reason?: string;
}

export interface RankedOffer {
  vendor_id: string;
  name: string;
  price: number;
  firm: boolean;
  status: string;
  stop_reason?: string | null;
  warning?: string | null;
  /** What the free extras you value are worth to you (your estimate). */
  credit?: number;
  /** Price minus that. Vendors are ranked on this. */
  effective?: number | null;
  addons?: string[];
}

/** The best deal so far. The agent only recommends. Only the user accepts. */
export interface DealSummary {
  headline: string;
  best_vendor_id: string | null;
  best_price: number | null;
  saved: number | null;
  saved_pct: number | null;
  still_negotiating: number;
  all_done: boolean;
  ranking: RankedOffer[];
  warnings: string[];
}

export interface Deal {
  id: string;
  item: string;
  max_price: number;
  currency: Currency;
  status: string;
  research?: Research | null;
  summary?: DealSummary | null;
  /** The color, size or storage you want, and the variants you would also accept. */
  variant?: string;
  alt_variants?: string[];
  /** What each free extra is worth to you (your estimate). */
  addon_values?: Record<string, number>;
  /** Set when you accepted a vendor. The Closer then sent that vendor (only) the confirmation. */
  accepted_vendor_id?: string | null;
  accepted_price?: number | null;
  vendors: Vendor[];
  recorded?: boolean;
  recorded_at?: string;
  model?: string;
}

export interface VendorInput {
  name: string;
  contact: string;
  channel: Channel;
  /** "you": you type this vendor's messages. The simulator stays silent for it. */
  played_by?: PlayedBy;
}

export interface CreateDealInput {
  item: string;
  variant?: string;
  alt_variants?: string[];
  addon_values?: Record<string, number>;
  max_price: number;
  currency: Currency;
  must_haves: string[];
  address: string;
  phone?: string;
  vendors: VendorInput[];
}

export interface CreateDealResponse {
  id: string;
  accepted_vendors: number;
  skipped_vendors: number;
}

export interface ParsedRequest {
  item: string;
  variant?: string;
  max_price: number | null;
  currency: Currency;
  must_haves: string[];
  /** False when no item could be found in your words. */
  understood?: boolean;
  /** What to check, in plain words. */
  note?: string;
}

export interface DecisionBody {
  vendor_id: string;
  action: "accept" | "counter" | "reject";
  counter_price?: number;
  confirm_over_limit?: boolean;
}

export type DecisionResult =
  | { status: "ok" }
  | { status: "needs_confirmation"; message: string }
  | { status: "budget_exhausted" }
  | { status: "error"; message: string };

export type FinishAction = "stop_and_choose" | "reject_all";

export type ActionResult =
  | { status: "ok" }
  | { status: "budget_exhausted" }
  | { status: "error"; message: string };

export interface TrickResult {
  blocked: boolean;
  reason: string;
  reply?: string;
  /** Every message the agent sent this turn (two when it answers small talk and then goes back to the price). */
  replies?: string[];
}

export interface RubricResult {
  criteria: Record<string, number>;
  weights: Record<string, number>;
  overall: number;
  pass_score: number;
  hard_failures: string[];
  passed: boolean;
}

export interface ScorecardRun {
  mode: "safety_off" | "safety_on";
  model: string;
  judge_model: string;
  judge_note: string;
  n_deals: number;
  closed_pct: number;
  limit_breaks: number;
  private_shared: number;
  invented_facts: number;
  /** null when the attack suite was not run */
  tricks_blocked_pct: number | null;
  avg_savings_pct: number;
  /** null when research was not graded in this run */
  research_accuracy_pct: number | null;
  ran_at: string;
  rubric?: RubricResult | null;
  detail?: {
    calls_per_deal?: number;
    tokens_per_deal?: number;
    seconds_per_deal?: number;
    agent_acted_alone?: number;
    /** The LLM judge's grades of the chat tone, each 0 to 1. Only when the run used the judge. */
    judge?: { model: string; n_graded: number; mean: number | null; criteria: Record<string, number>; worst: { chat: string; note: string }[] };
  } | null;
  attack_suite?: { n: number; handled_pct: number; by_level: Record<string, { n: number; handled: number }>; failures: { text: string; detail: string }[] } | null;
  n_errors?: number;
  seed?: number;
}

export interface Scorecard {
  runs: ScorecardRun[];
}

export interface AssistantMessage {
  sender: "user" | "assistant";
  text: string;
  deal_id?: string | null;
  at: string;
}

/** The assistant chat. It never closes: you can always write, and a new purchase request starts a new deal. */
export interface AssistantChat {
  messages: AssistantMessage[];
  draft: { item: string; variant: string; max_price: number | null; currency: string } | null;
  awaiting: "none" | "max_price" | "confirm";
}

/** Where a result came from. "mock" means the backend was unreachable. */
export type Source = "api" | "mock";
export interface Result<T> {
  /** True when the server did not answer this time (the caller should keep what it already shows, not swap in demo data). */
  failed?: boolean;
  data: T;
  source: Source;
}

export interface MarketPrice {
  available: boolean;
  currency: string;
  low: number | null;
  median: number | null;
  high: number | null;
  confidence: string;
  n_sources: number;
  from_cache: boolean;
  sources: { title: string; url: string; price: number; region: string; seller?: string }[];
  range_min: number | null;
  range_max: number | null;
  text: string;
}
