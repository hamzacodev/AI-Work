"use client";

import { useState } from "react";
import ConfirmDialog from "@/components/ConfirmDialog";
import { btnGhost, btnPrimary, StatusBadge } from "@/components/ui";
import { finishDeal, sendDecision } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import type { Deal, VendorStatus } from "@/lib/types";

const REASONS: Record<string, string> = {
  firm_price: "said the price is final",
  round_limit: "rounds used",
  good_price: "good price, waiting for the others",
  near_market_low: "already close to the lowest market price",
  met_counter: "close to our last offer",
  at_limit: "at the most the agent offers on its own",
  stalled: "repeats the same price",
  injection: "blocked by the Safety Guard",
  stopped_by_user: "you stopped the negotiation",
  accepted: "you accepted this vendor",
  other_vendor_accepted: "closed, you accepted another vendor",
  rejected_by_user: "you rejected this vendor",
};

interface Props {
  deal: Deal;
  onOpen: (vendorId: string) => void;
  onChanged: () => void;
  onBudgetExhausted: () => void;
}

/**
 * The final pick and the notification area. The agent negotiates in every chat, then shows ONE best deal here.
 * You press Accept or Reject in this one place. The agent never accepts: only you can.
 */
export default function BestDeal({ deal, onOpen, onChanged, onBudgetExhausted }: Props) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [choose, setChoose] = useState(false);
  const [pick, setPick] = useState("");
  const [confirm, setConfirm] = useState<{ text: string; vendorId: string } | null>(null);

  const s = deal.summary;
  if (!s || s.ranking.length === 0) return null;
  const money = (n: number) => formatMoney(n, deal.currency);
  const status = (id: string): VendorStatus => deal.vendors.find((v) => v.id === id)?.status ?? "negotiating";
  const accepted = deal.status === "accepted" && deal.accepted_vendor_id;
  const rejected = deal.status === "rejected";
  const decided = Boolean(accepted) || rejected;
  const open = s.ranking.filter((r) => status(r.vendor_id) !== "closed" && status(r.vendor_id) !== "blocked");
  const best = s.best_vendor_id && open.some((r) => r.vendor_id === s.best_vendor_id) ? s.ranking.find((r) => r.vendor_id === s.best_vendor_id) : open[0];
  const bestVendor = deal.vendors.find((v) => v.id === best?.vendor_id);
  const bestName = bestVendor?.name ?? "";
  const accepts = (deal.alt_variants ?? []).map((x) => x.toLowerCase());
  const cheaperVariant = bestVendor
    ? Object.entries(bestVendor.variant_prices ?? {})
        .filter(([variant, price]) => price < (best?.price ?? 0) && accepts.some((a) => a.includes(variant.toLowerCase()) || variant.toLowerCase().includes(a.split(",")[0].trim())))
        .map(([variant, price]) => ({ variant, price, diff: (best?.price ?? 0) - price }))
        .sort((x, y) => y.diff - x.diff)[0]
    : undefined;
  const nameOf = (id: string | null | undefined) => deal.vendors.find((v) => v.id === id)?.name ?? "the vendor";

  async function accept(vendorId: string, confirmOver = false) {
    setBusy(true);
    setMsg("");
    const { data } = await sendDecision(deal.id, { vendor_id: vendorId, action: "accept", confirm_over_limit: confirmOver || undefined });
    setBusy(false);
    if (data.status === "ok") {
      setConfirm(null);
      onChanged();
    } else if (data.status === "needs_confirmation") setConfirm({ text: data.message, vendorId });
    else if (data.status === "budget_exhausted") onBudgetExhausted();
    else setMsg(data.message);
  }

  async function finish(action: "stop_and_choose" | "reject_all") {
    setBusy(true);
    setMsg("");
    const { data } = await finishDeal(deal.id, action);
    setBusy(false);
    if (data.status === "ok") onChanged();
    else if (data.status === "error") setMsg(data.message);
  }

  return (
    <section aria-label="Best deal so far" className="rounded-xl border border-accent bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-medium text-text-primary">
            {accepted ? "Deal accepted" : rejected ? "No deal" : s.all_done ? "Final pick" : "Best deal so far"}
          </h2>
          <p className="mt-1 text-sm text-text-primary">
            {accepted
              ? `You accepted ${nameOf(deal.accepted_vendor_id)} at ${money(deal.accepted_price ?? 0)}. The Closer sent that vendor, and only that vendor, the confirmation with cash on delivery and your address. The other chats are closed.`
              : rejected
                ? "You rejected every vendor. Nothing was sent to anyone."
                : s.headline}
          </p>
        </div>
        {s.best_vendor_id && !decided && (
          <button type="button" onClick={() => onOpen(s.best_vendor_id as string)} className={btnGhost}>
            Open the best chat
          </button>
        )}
      </div>

      <ol className="mt-3 divide-y divide-border rounded-md border border-border">
        {s.ranking.map((r, i) => (
          <li key={r.vendor_id}>
            <button
              type="button"
              onClick={() => onOpen(r.vendor_id)}
              className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-left text-sm hover:bg-surface-2"
            >
              <span className="w-5 text-text-secondary">{i + 1}</span>
              <span className="min-w-0 flex-1 truncate font-medium text-text-primary">{r.name}</span>
              <span className="text-text-primary">{money(r.price)}</span>
              {(r.credit ?? 0) > 0 && r.effective != null && (
                <span className="text-xs text-accent" title="Price minus the free extras you value. Your estimate.">
                  {money(r.effective)} with {r.addons?.join(", ")}
                </span>
              )}
              {r.firm && <span className="rounded-full border border-border px-2 py-0.5 text-xs text-text-secondary">firm</span>}
              <StatusBadge status={status(r.vendor_id)} reason={deal.vendors.find((v) => v.id === r.vendor_id)?.stop_reason} />
              {(r.stop_reason || deal.vendors.find((v) => v.id === r.vendor_id)?.stop_reason) && (
                <span className="w-full pl-8 text-xs text-text-secondary">
                  {REASONS[deal.vendors.find((v) => v.id === r.vendor_id)?.stop_reason ?? r.stop_reason ?? ""] ?? r.stop_reason}
                </span>
              )}
              {r.warning && <span className="w-full pl-8 text-xs text-warn-text">{r.warning}</span>}
            </button>
          </li>
        ))}
      </ol>

      {cheaperVariant && (
        <p className="mt-3 rounded-md bg-surface-2 px-3 py-2 text-sm text-text-primary">
          At {bestName}, {cheaperVariant.variant} is {money(cheaperVariant.diff)} cheaper ({money(cheaperVariant.price)}), and you said you would
          accept it. Ask the vendor about it in the chat. The agent does not switch your variant by itself.
        </p>
      )}

      {!decided && best && s.all_done && best.price > deal.max_price && (
        <p className="mt-4 rounded-md bg-surface-2 px-3 py-2 text-sm text-text-primary">
          The lowest offer is <strong>{money(best.price)}</strong> from {best.name}. That is {money(best.price - deal.max_price)} (
          {(((best.price - deal.max_price) / deal.max_price) * 100).toFixed(1)}%) above your maximum of {money(deal.max_price)}.
          {(best.price - deal.max_price) / deal.max_price <= 0.1
            ? " That is a small gap. If a few dollars do not matter to you, you can accept it. You will be asked to confirm first, so nothing is sent by mistake."
            : " That is a big gap. You can still accept it, after a confirmation, or reject it."}
        </p>
      )}

      {!decided && best && (
        <div className="mt-4 space-y-3">
          {s.all_done ? (
            <div className="flex flex-wrap gap-2">
              <button type="button" disabled={busy} className={btnPrimary} onClick={() => accept(best.vendor_id)}>
                Accept {best.name} at {money(best.price)}{best.price > deal.max_price ? " (above your maximum)" : ""}
              </button>
              <button type="button" disabled={busy} className={btnGhost} onClick={() => setChoose((c) => !c)}>
                Choose a different vendor
              </button>
              <button type="button" disabled={busy} className={btnGhost} onClick={() => finish("reject_all")}>
                Reject all
              </button>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" disabled={busy} className={btnGhost} onClick={() => finish("stop_and_choose")}>
                Stop and choose now
              </button>
              <span className="text-xs text-text-secondary">
                The agent is still negotiating with {s.still_negotiating} vendor{s.still_negotiating === 1 ? "" : "s"}. You can wait for
                the final pick, or stop now and choose.
              </span>
            </div>
          )}

          {choose && (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-border p-3">
              <label htmlFor="pick" className="text-sm text-text-secondary">Accept this vendor instead</label>
              <select id="pick" value={pick} onChange={(e) => setPick(e.target.value)} className="rounded-md border border-border bg-background px-2 py-1.5 text-sm text-text-primary">
                <option value="">Choose a vendor</option>
                {open.map((r) => (
                  <option key={r.vendor_id} value={r.vendor_id}>
                    {r.name}, {money(r.price)}
                  </option>
                ))}
              </select>
              <button type="button" disabled={busy || !pick} className={btnPrimary} onClick={() => accept(pick)}>
                Accept
              </button>
            </div>
          )}
        </div>
      )}

      {msg && <p role="alert" className="mt-3 text-sm text-danger-text">{msg}</p>}
      <p className="mt-2 text-xs text-text-secondary">
        The agent never accepts a deal. It only recommends. Vendors are compared on the price minus the free extras you value (your own
        estimate). Check delivery and the must-have features too.
      </p>

      {confirm && <ConfirmDialog message={confirm.text} onCancel={() => setConfirm(null)} onConfirm={() => accept(confirm.vendorId, true)} />}
    </section>
  );
}
