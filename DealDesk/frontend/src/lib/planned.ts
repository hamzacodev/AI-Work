// Content for the Planned pages (docs/frontend.md, part 3).
// None of these have an engine behind them. They only explain the roadmap.

export type Group = "Money and business" | "Daily life" | "Work";

export interface PlannedItem {
  slug: string;
  title: string;
  group: Group;
  live?: boolean;
  does: string;
  sides?: string;
  rule?: string;
  closing?: string;
  reuses: string[];
}

const ALL = [
  "Researcher",
  "Negotiator",
  "Safety Guard",
  "Fact Checker",
  "Limit Checker",
  "Closer",
];

export const items: PlannedItem[] = [
  {
    slug: "buy",
    title: "Buy from vendors",
    group: "Money and business",
    live: true,
    does: "Negotiates with many vendors for you, researches the real price and asks you only for real decisions.",
    reuses: ALL,
  },
  {
    slug: "sell",
    title: "Sell",
    group: "Money and business",
    does: "Handles buyers who write to you.",
    sides: "Seller or buyer.",
    rule: "Never go below your minimum. Never hand over before payment is confirmed.",
    closing: "Confirms payment and shares pickup details.",
    reuses: ["Negotiator", "Safety Guard", "Fact Checker", "Limit Checker", "Closer"],
  },
  {
    slug: "get-an-investor",
    title: "Get an investor",
    group: "Money and business",
    does: "Researches investors, writes outreach and answers their questions.",
    sides: "Founder or investor.",
    rule: "Never invent numbers. Never share the cap table.",
    closing: "Sends the deck and meeting slots.",
    reuses: ["Researcher", "Negotiator", "Safety Guard", "Fact Checker", "Limit Checker", "Closer"],
  },
  {
    slug: "review-pitches",
    title: "Review pitches",
    group: "Money and business",
    does: "Researches founders and replies with approved information only.",
    sides: "Investor.",
    rule: "Reply only with information you approved.",
    closing: "Asks for the deck and sends meeting slots.",
    reuses: ["Researcher", "Safety Guard", "Fact Checker", "Limit Checker", "Closer"],
  },
  {
    slug: "freelance-rates",
    title: "Freelance rates and client payments",
    group: "Money and business",
    does: "Negotiates rates, chases late invoices and offers payment plans.",
    rule: "Never go below your minimum rate.",
    closing: "Confirms the scope and the payment plan.",
    reuses: ["Researcher", "Negotiator", "Safety Guard", "Fact Checker", "Limit Checker", "Closer"],
  },
  {
    slug: "sponsors",
    title: "Sponsors and partnerships",
    group: "Money and business",
    does: "Handles offers from brands.",
    rule: "Only the terms you approved.",
    closing: "Confirms the deal terms.",
    reuses: ["Negotiator", "Safety Guard", "Fact Checker", "Limit Checker", "Closer"],
  },
  {
    slug: "rent-a-house",
    title: "Rent a house",
    group: "Daily life",
    does: "Researches local rents, negotiates, and asks for pictures, a video and documents.",
    sides: "Tenant or landlord.",
    rule: "No advance money before you have seen the place.",
    closing: "Books the visit and handles the agreement.",
    reuses: ALL,
  },
  {
    slug: "rent-out-a-house",
    title: "Rent out a house",
    group: "Daily life",
    does: "Handles tenants who write to you.",
    rule: "Ask for ID and references before booking a visit.",
    closing: "Books the visit and sends the agreement after you approve.",
    reuses: ["Negotiator", "Safety Guard", "Fact Checker", "Limit Checker", "Closer"],
  },
  {
    slug: "used-items",
    title: "Used items",
    group: "Daily life",
    does: "Handles buyers and sellers on marketplaces.",
    rule: "Your minimum price when selling, your maximum price when buying.",
    closing: "Confirms the price and the handover.",
    reuses: ALL,
  },
  {
    slug: "bills-and-services",
    title: "Bills and services",
    group: "Daily life",
    does: "Negotiates or cancels internet, insurance and subscriptions.",
    rule: "Never accept a longer contract than you approved.",
    closing: "Confirms the new price or the cancellation.",
    reuses: ["Researcher", "Negotiator", "Safety Guard", "Fact Checker", "Limit Checker", "Closer"],
  },
  {
    slug: "find-a-job",
    title: "Find a job and negotiate salary",
    group: "Work",
    does: "Contacts recruiters, researches market pay, and negotiates salary and benefits.",
    sides: "Candidate or employer.",
    rule: "Never go below your minimum salary. Share only what is in your CV.",
    closing: "Sends your CV and availability, confirms the interview and negotiates the offer.",
    reuses: ALL,
  },
  {
    slug: "hire",
    title: "Hire",
    group: "Work",
    does: "Screens candidates and schedules interviews.",
    rule: "Screen only against your requirements.",
    closing: "Offers interview slots. An offer goes out only after you decide.",
    reuses: ["Safety Guard", "Fact Checker", "Limit Checker", "Closer"],
  },
];

export const groups: { name: Group; label: string }[] = [
  { name: "Money and business", label: "Money and business" },
  { name: "Daily life", label: "Daily life" },
  { name: "Work", label: "Work" },
];

export function findItem(slug: string): PlannedItem | undefined {
  return items.find((i) => i.slug === slug);
}
