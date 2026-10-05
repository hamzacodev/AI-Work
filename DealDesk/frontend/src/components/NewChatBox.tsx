"use client";

import { useState } from "react";
import { btnGhost, btnPrimary, inputCls } from "@/components/ui";
import { marketPrice, parseRequest } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import type { MarketPrice, ParsedRequest } from "@/lib/types";

/** Dummy vendors for the demonstration. You play whichever ones you pick. */
export const DEMO_VENDORS = ["TechHub Store", "Digital Bazar", "Gadget World", "Prime Electronics"];

/** The buyer's maximum in this demo when the sentence has none. It is a dummy value, and it is never shown to the vendor. */
export const DEMO_MAX = 1000;

export interface NewChatRequest {
  item: string; // the item with its variant, for example "macbook 2018"
  mustHaves: string[];
  maxPrice: number;
  currency: ParsedRequest["currency"];
  vendors: string[];
}

/**
 * "New chat" on the WhatsApp page: write what the buyer wants, pick the vendors, and one chat opens for each vendor you pick.
 * It is only a demonstration of the conversation, so there is no maximum to fill in (a dummy one is used).
 */
/** The item with its variant, without repeating words the item already has ("512 gb harddisk 512 gb harddisk"). */
function withVariant(p: ParsedRequest): string {
  const v = (p.variant ?? "").trim();
  return v && !p.item.toLowerCase().includes(v.toLowerCase()) ? `${p.item} ${v}` : p.item;
}

export default function NewChatBox({ opened, onStart }: { opened: string[]; onStart: (r: NewChatRequest) => void }) {
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<ParsedRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState<string[]>([DEMO_VENDORS[0]]);
  const [market, setMarket] = useState<MarketPrice | null>(null);
  const [checking, setChecking] = useState(false);
  const [marketError, setMarketError] = useState("");

  async function understand(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim() || busy) return;
    setBusy(true);
    const { data } = await parseRequest(text.trim());
    setBusy(false);
    setParsed(data);
    setPicked([DEMO_VENDORS[0]]);
    setMarket(null);
    if (data.item) void checkMarket(data);
  }

  /** The real price research (web search, cached 24 hours). The demo agent then uses this market price. */
  async function checkMarket(p: ParsedRequest) {
    setChecking(true);
    setMarketError("");
    const r = await marketPrice(withVariant(p), p.must_haves, p.currency);
    setChecking(false);
    setMarket(r.data);
    if (r.error) setMarketError(r.error);
  }

  function toggle(name: string) {
    setPicked((p) => (p.includes(name) ? p.filter((x) => x !== name) : [...p, name]));
  }

  function start() {
    if (!parsed?.item || picked.length === 0) return;
    // With a real market price, the dummy maximum is set so the demo agent sees that market price (its demo market is 87.5% of the maximum).
    const fromMarket = market?.available && market.median && market.confidence !== "low" ? Math.ceil(market.median / 0.875) : null;
    onStart({ item: fullItem, mustHaves: parsed.must_haves, maxPrice: parsed.max_price ?? fromMarket ?? DEMO_MAX, currency: parsed.currency, vendors: picked });
    setPicked([]);
  }

  const fullItem = parsed ? withVariant(parsed) : "";
  const free = DEMO_VENDORS.filter((v) => !opened.includes(`${fullItem}|${v}`));

  return (
    <section aria-label="New chat" className="rounded-2xl border border-border bg-surface shadow-card p-4">
      <h2 className="font-medium text-text-primary">New chat</h2>
      <p className="mt-1 text-sm text-text-secondary">
        Write what the buyer wants, for example <em>I want to buy a macbook 2018 with 16GB RAM</em>. Then pick the vendors. One chat opens for
        each vendor, and you answer as that vendor. The buyer&apos;s maximum price is a dummy value here, so you do not need to type one.
      </p>
      <form onSubmit={understand} className="mt-3 flex gap-2">
        <input
          aria-label="What the buyer wants"
          value={text}
          maxLength={500}
          onChange={(e) => setText(e.target.value)}
          placeholder="I want to buy ..."
          className={inputCls}
        />
        <button type="submit" disabled={busy || !text.trim()} className={btnGhost}>
          {busy ? "Reading" : "Understand"}
        </button>
      </form>

      {parsed && !parsed.item && <p className="mt-3 text-sm text-text-secondary">I could not find what to buy. Write it again, for example: I want to buy a Dell XPS 15.</p>}
      {parsed?.item && (
        <div className="mt-3 rounded-md border border-border bg-background p-3 text-sm">
          <p className="text-text-primary">
            Buying: <span className="font-medium">{fullItem}</span>
            {parsed.must_haves.length > 0 && <span className="text-text-secondary">, must have {parsed.must_haves.join(", ")}</span>}
          </p>
          <div className="mt-3 rounded-md border border-border p-3" aria-live="polite">
            <p className="text-xs text-text-secondary">Market price research</p>
            {checking && <p className="mt-1 text-text-primary">Searching the web for the price. This can take up to a minute.</p>}
            {!checking && market?.available && market.low !== null && market.median !== null && (
              <>
                <p className="mt-1 text-text-primary">
                  {formatMoney(market.low, market.currency)} to {formatMoney(market.high ?? market.low, market.currency)}, typical{" "}
                  {formatMoney(market.median, market.currency)} ({market.confidence} confidence, {market.n_sources} source{market.n_sources === 1 ? "" : "s"}
                  {market.from_cache ? ", saved result" : ""}).
                </p>
                {market.confidence === "low" && (
                  <p className="mt-1 text-xs text-text-secondary">
                    Low confidence: the prices do not agree, so the demo does not use this range. It uses a dummy price instead. Name the exact model for a better range.
                  </p>
                )}
                <ul className="mt-2 space-y-1 text-xs">
                  {market.sources.slice(0, 4).map((src) => (
                    <li key={src.url} className="truncate">
                      {formatMoney(src.price, market.currency)} ·{" "}
                      <a href={src.url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                        {src.title || src.url}
                      </a>
                    </li>
                  ))}
                </ul>
                {market.confidence !== "low" && <p className="mt-2 text-xs text-text-secondary">The demo buyer agent uses this market price when it talks to the vendors.</p>}
              </>
            )}
            {!checking && !market?.available && (
              <p className="mt-1 text-text-secondary">
                {(marketError || (market?.text ?? "No market price found.")).replace(/\s*Enter the maximum you want to pay\.?/i, "")} The demo uses a dummy price instead.{" "}
                <button type="button" className="text-accent hover:underline" onClick={() => parsed && void checkMarket(parsed)}>
                  Search again
                </button>
              </p>
            )}
          </div>
          <fieldset className="mt-3">
            <legend className="text-xs text-text-secondary">Pick the vendors to chat with</legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {DEMO_VENDORS.map((v) => {
                const used = !free.includes(v);
                return (
                  <label key={v} className={`flex items-center gap-2 rounded-full border border-border px-3 py-1 text-sm ${used ? "opacity-50" : "cursor-pointer hover:bg-surface-2"}`}>
                    <input type="checkbox" disabled={used} checked={picked.includes(v) && !used} onChange={() => toggle(v)} />
                    {v}
                    {used && <span className="text-xs text-text-secondary">chat open</span>}
                  </label>
                );
              })}
            </div>
          </fieldset>
          <button type="button" disabled={picked.length === 0} className={`${btnPrimary} mt-3`} onClick={start}>
            Start {picked.length > 1 ? `${picked.length} chats` : "the chat"}
          </button>
        </div>
      )}
    </section>
  );
}
