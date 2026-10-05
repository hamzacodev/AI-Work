import type { VendorStatus } from "@/lib/types";

export function Chip({ live }: { live: boolean }) {
  return live ? (
    <span className="rounded-full bg-accent-800 px-2.5 py-0.5 text-xs font-medium text-accent-50">
      Live
    </span>
  ) : (
    <span className="rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-xs font-medium text-text-secondary">
      Planned
    </span>
  );
}

const STATUS: Record<VendorStatus, { label: string; cls: string }> = {
  sent: { label: "Sent", cls: "bg-surface-2 text-text-secondary border border-border" },
  replied: { label: "Replied", cls: "bg-accent-900 text-accent-100" },
  negotiating: { label: "Negotiating", cls: "bg-accent-800 text-accent-50" },
  paused: { label: "Paused", cls: "bg-surface-2 text-text-secondary border border-border" },
  needs_you: { label: "Needs you", cls: "bg-warn-100 text-warn-900" },
  closed: { label: "Deal done", cls: "bg-surface-2 text-text-primary border border-border" },
  blocked: { label: "Blocked", cls: "bg-danger-100 text-danger-900" },
};

// A closed vendor is not always a "deal done": only the accepted one is. A rejected or passed-over vendor says so.
const CLOSED_BY: Record<string, { label: string; cls: string }> = {
  accepted: STATUS.closed,
  rejected_by_user: { label: "Rejected by you", cls: "bg-surface-2 text-text-secondary border border-border" },
  other_vendor_accepted: { label: "Closed", cls: "bg-surface-2 text-text-secondary border border-border" },
};

// The agent stopped texting for a normal reason (a good or final price, a clear no, the rounds were used). Nothing is needed from you
// until every chat is finished, so these are NOT "Needs you". "Needs you" is for real problems (a message to check, a model error).
export const NORMAL_STOPS = ["good_price", "near_market_low", "met_counter", "at_limit", "stalled", "round_limit", "firm_price", "refused"];
export const isNormalStop = (status: string, reason?: string | null) => status === "needs_you" && !!reason && NORMAL_STOPS.includes(reason);

export function StatusBadge({ status, reason }: { status: VendorStatus; reason?: string | null }) {
  const s = isNormalStop(status, reason)
    ? STATUS.paused
    : ((status === "closed" && reason ? CLOSED_BY[reason] : undefined) ?? STATUS[status]);
  return (
    <span className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${s.cls}`}>
      {s.label}
    </span>
  );
}

export function DemoBanner({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <p className="mb-4 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-secondary">
      Demo data. The backend is not connected, so this page uses sample data.
    </p>
  );
}

export const inputCls =
  "w-full rounded-md border border-border bg-background px-3 py-2 text-text-primary placeholder:text-text-secondary";

export const btnPrimary =
  "rounded-full bg-primary px-5 py-2 font-medium text-on-primary hover:bg-primary-hover disabled:opacity-60";

export const btnGhost =
  "rounded-full border border-border px-4 py-2 text-sm text-text-primary hover:bg-surface-2 disabled:opacity-60";
