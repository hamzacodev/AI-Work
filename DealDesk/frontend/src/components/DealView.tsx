"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import BestDeal from "@/components/BestDeal";
import { AgentAvatar, Avatar } from "@/components/chat/Avatar";
import ChatList, { type ChatListItem } from "@/components/chat/ChatList";
import ChatPane from "@/components/chat/ChatPane";
import ControlPanel from "@/components/ControlPanel";
import { btnPrimary, DemoBanner, isNormalStop, StatusBadge } from "@/components/ui";
import { getDeal, getRecorded, retryResearch } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import type { Deal, Source, Vendor } from "@/lib/types";

const POLL_MS = 3000;

const FILTERS = [
  { key: "needs_you", label: "Needs you" },
  { key: "active", label: "Active" },
  { key: "done", label: "Closed" },
];

function tagsFor(v: Vendor): string[] {
  if (v.status === "needs_you" && !isNormalStop(v.status, v.stop_reason)) return ["needs_you", "active"];
  if (v.status === "closed" || v.status === "blocked") return ["done"];
  return ["active"]; // negotiating and paused (the agent stopped texting, the chat is still open)
}

function previewFor(v: Vendor): string {
  const last = v.messages[v.messages.length - 1];
  if (!last) return "No messages yet";
  const who = last.from === "agent" ? "DealDesk agent: " : last.from === "owner" ? "You: " : "";
  return who + last.text;
}

export default function DealView({ id, skipped }: { id: string; skipped: number }) {
  const [deal, setDeal] = useState<Deal | null>(null);
  const [source, setSource] = useState<Source>("api");
  const [selected, setSelected] = useState<string | null>(null);
  const [exhausted, setExhausted] = useState(false);
  const [recorded, setRecorded] = useState(false);
  const [missing, setMissing] = useState(false);
  const [researchMsg, setResearchMsg] = useState("");
  const [reconnecting, setReconnecting] = useState(false);
  const messengerRef = useRef<HTMLElement>(null);

  /** Opens a vendor chat. On a phone the chat sits below the summary, so scroll to it. */
  const openChat = useCallback((vendorId: string | null) => {
    setSelected(vendorId);
    requestAnimationFrame(() => messengerRef.current?.scrollIntoView({ block: "start" }));
  }, []);

  const refresh = useCallback(async () => {
    const r = await getDeal(id);
    if (r.failed) return; // keep the deal that is already on screen
    setDeal(r.data);
    setMissing(r.data === null);
    setSource(r.source);
  }, [id]);

  useEffect(() => {
    if (recorded) return;
    let cancelled = false;
    async function load() {
      const r = await getDeal(id);
      if (cancelled) return;
      if (r.failed) {
        setReconnecting(true); // keep the deal that is on screen and try again at the next poll
        return;
      }
      setReconnecting(false);
      setDeal(r.data);
      setMissing(r.data === null);
      setSource(r.source);
    }
    load();
    const t = setInterval(load, POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [id, recorded]);

  async function viewRecorded() {
    const r = await getRecorded();
    setDeal(r.data);
    setMissing(false);
    setSource(r.source);
    setRecorded(true);
    setExhausted(false);
    setSelected(null);
  }

  if (missing) return <p role="alert" className="text-text-primary">This deal was not found. Start a new one from the Buy page.</p>;
  if (!deal) return <p role="status" className="text-text-secondary">Loading the deal. If the server was asleep, this can take up to 30 seconds.</p>;

  const money = (n: number) => formatMoney(n, deal.currency);
  const vendor = deal.vendors.find((v) => v.id === selected) ?? null;
  const waiting = deal.vendors.filter((v) => v.status === "needs_you" && !isNormalStop(v.status, v.stop_reason));

  // The server sends vendors in no fixed order, so the list used to jump on every refresh. Newest message on top, ties by name.
  const lastAt = (v: (typeof deal.vendors)[number]) => {
    const t = v.messages.length ? Date.parse(v.messages[v.messages.length - 1].at) : 0;
    return Number.isNaN(t) ? 0 : t;
  };
  const ordered = [...deal.vendors].sort((a, b) => lastAt(b) - lastAt(a) || a.name.localeCompare(b.name) || a.id.localeCompare(b.id));

  const items: ChatListItem[] = ordered.map((v) => {
    const last = v.messages[v.messages.length - 1];
    return {
      id: v.id,
      name: v.name,
      avatar: <Avatar name={v.name} />,
      preview: previewFor(v),
      at: last?.at,
      meta: (v.offer_price !== null ? `Offer ${money(v.offer_price)}` : "No offer yet") + (v.played_by === "you" ? " · You play this vendor" : ""),
      badge: <StatusBadge status={v.status} reason={v.stop_reason} />,
      urgent: v.status === "needs_you" && !isNormalStop(v.status, v.stop_reason),
      highlight: Boolean(deal.summary?.all_done && deal.status === "negotiating" && deal.summary.best_vendor_id === v.id),
      tags: tagsFor(v),
    };
  });

  return (
    <div className="space-y-6">
      <DemoBanner show={source === "mock"} />
      {reconnecting && (
        <p role="status" className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-secondary">
          The server did not answer just now. Your deal is safe. Trying again in a few seconds.
        </p>
      )}

      {skipped > 0 && (
        <p className="rounded-md bg-warn-100 px-3 py-2 text-sm text-warn-900">
          {skipped} vendors were skipped. Only the first 10 vendors are processed in one deal.
        </p>
      )}

      {exhausted && (
        <div role="alert" className="rounded-md border border-border bg-surface p-3">
          <p className="text-text-primary">Demo limit reached, try tomorrow.</p>
          <button type="button" className={`${btnPrimary} mt-2`} onClick={viewRecorded}>
            View a recorded run
          </button>
        </div>
      )}

      {deal.recorded && (
        <p className="rounded-md bg-accent-900 px-3 py-2 text-sm text-accent-100">
          Recorded run{deal.recorded_at ? `, saved ${formatDate(deal.recorded_at)}` : ""}
          {deal.model ? `, model: ${deal.model}` : ""}. This is not live.
        </p>
      )}

      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-text-secondary">Your purchase</p>
          <h1 className="text-2xl font-semibold text-text-primary">{deal.item}</h1>
          <p className="mt-1 text-text-secondary">Your maximum: {money(deal.max_price)} · Status: {deal.status}</p>
        </div>
        {waiting.length > 0 && !recorded && deal.summary?.all_done && (
          <button type="button" className={btnPrimary} onClick={() => openChat(waiting[0].id)}>
            {waiting.length} waiting for your decision
          </button>
        )}
      </header>

      {!recorded && <BestDeal deal={deal} onOpen={openChat} onChanged={refresh} onBudgetExhausted={() => setExhausted(true)} />}

      {!recorded && <ControlPanel deal={deal} onChanged={refresh} />}

      {deal.research && deal.research.available === false && (
        <section aria-label="Research summary" className="rounded-2xl border border-border bg-surface shadow-card p-4">
          <h2 className="font-medium text-text-primary">Market price research</h2>
          <p className="mt-2 text-sm text-text-secondary">
            No reliable market price was found, so the agent will not guess a price. {deal.research.reason} The vendors still get the
            first message, and you can counter by hand.
          </p>
          {!recorded && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className={btnPrimary}
                onClick={async () => {
                  setResearchMsg("Searching again. The page updates by itself.");
                  const r = await retryResearch(deal.id);
                  if (r.status === "error") setResearchMsg(r.message);
                  else refresh();
                }}
              >
                Search again
              </button>
              <span className="text-xs text-text-secondary">It uses search credits (about 6). {researchMsg}</span>
            </div>
          )}
        </section>
      )}

      {deal.research && deal.research.available !== false && deal.research.low !== null && deal.research.median !== null && deal.research.high !== null && (
        <section aria-label="Research summary" className="rounded-2xl border border-border bg-surface shadow-card p-4">
          <h2 className="font-medium text-text-primary">{deal.research.confidence === "low" ? "Price to beat" : "Market price research"}</h2>
          {deal.research.confidence === "low" ? (
            <>
              {/* The search found prices that do not agree, so a range would only confuse. One price is shown: your maximum. */}
              <p className="mt-3 text-sm text-text-secondary">Your maximum</p>
              <p className="text-3xl font-semibold text-text-primary">{money(deal.max_price)}</p>
              <p className="mt-2 text-sm text-text-secondary">
                The market search was not reliable (the prices it found do not agree), so the agent does not quote a market price. It
                negotiates from the vendors&apos; own prices, shares the best competing price, and never offers more than 95% of your maximum.
              </p>
              <details className="mt-3 text-sm">
                <summary className="cursor-pointer text-text-secondary">What the search found (not trusted)</summary>
                <p className="mt-2 text-text-primary">
                  {money(deal.research.low)} to {money(deal.research.high)}, from {deal.research.n_sources} source{deal.research.n_sources === 1 ? "" : "s"}.
                </p>
                <p className="mt-1 text-xs text-text-secondary">{deal.research.reason || deal.research.note}</p>
              </details>
            </>
          ) : (
            <>
              <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
                {[
                  ["Low", money(deal.research.low)],
                  ["Median", money(deal.research.median)],
                  ["High", money(deal.research.high)],
                  ["Sources", String(deal.research.n_sources)],
                  ["Confidence", deal.research.confidence],
                ].map(([k, v]) => (
                  <div key={k}>
                    <dt className="text-text-secondary">{k}</dt>
                    <dd className="text-lg font-medium text-text-primary">{v}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-3 text-xs text-text-secondary">{deal.research.note}</p>
            </>
          )}
        </section>
      )}

      <section ref={messengerRef} aria-label="Vendor conversations" className="scroll-mt-4">
        <div className="grid h-[calc(100dvh-8rem)] max-h-[48rem] min-h-[32rem] overflow-hidden rounded-xl border border-border lg:grid-cols-[22rem_1fr]">
          <div className={`${selected ? "hidden lg:flex" : "flex"} min-h-0 flex-col border-border lg:border-r`}>
            <ChatList
              title="Vendors"
              items={items}
              selectedId={selected}
              onSelect={openChat}
              filters={FILTERS}
              searchLabel="Search vendors"
            />
          </div>

          <div className={`${selected ? "flex" : "hidden lg:flex"} min-h-0 min-w-0 flex-col`}>
            {vendor ? (
              <ChatPane
                key={vendor.id}
                deal={deal}
                vendor={vendor}
                readOnly={recorded}
                onBack={() => openChat(null)}
                onChanged={refresh}
                onBudgetExhausted={() => setExhausted(true)}
              />
            ) : (
              <div className="flex h-full flex-col items-center justify-center gap-3 bg-background p-8 text-center">
                <AgentAvatar size={56} />
                <h2 className="text-lg font-semibold text-text-primary">Pick a vendor to read the chat</h2>
                <p className="max-w-sm text-sm text-text-secondary">
                  Your DealDesk agent talks to each vendor for you. In every chat, the vendor is on the left, and your
                  agent and you are on the right.
                </p>
              </div>
            )}
          </div>
        </div>
        <p className="mt-2 text-xs text-text-secondary">
          {recorded ? "Recorded run, updates are off." : "Updates every 3 seconds."}
        </p>
      </section>
    </div>
  );
}
