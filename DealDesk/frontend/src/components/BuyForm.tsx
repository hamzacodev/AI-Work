"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import VendorTable from "@/components/VendorTable";
import { btnGhost, btnPrimary, DemoBanner, inputCls } from "@/components/ui";
import { createDeal, marketPrice, parseRequest } from "@/lib/api";
import { formatMoney } from "@/lib/format";
import { ADDONS } from "@/lib/addons";
import { CURRENCIES, type Currency, type MarketPrice } from "@/lib/types";
import { findProblems, newKey, type VendorRow } from "@/lib/vendors";

const SAMPLE: Omit<VendorRow, "key">[] = [
  { name: "TechHub Store", contact: "sales@techhub.example.com", channel: "chat", played_by: "you" },
  { name: "Gadget World", contact: "hello@gadgetworld.example.com", channel: "chat", played_by: "you" },
  { name: "Laptop Mart", contact: "orders@laptopmart.example.com", channel: "chat", played_by: "you" },
  { name: "Digital Bazaar", contact: "+92 300 1234567", channel: "chat", played_by: "you" },
  { name: "Prime Electronics", contact: "deals@primeelectronics.example.com", channel: "chat", played_by: "you" },
];

const label = "text-sm text-text-secondary";

export default function BuyForm() {
  const router = useRouter();
  const [chat, setChat] = useState("I want to buy a Dell XPS 15 under $800 with 16GB RAM");
  const [parsing, setParsing] = useState(false);
  const [usedMock, setUsedMock] = useState(false);
  const [notice, setNotice] = useState("");
  const [market, setMarket] = useState<MarketPrice | null>(null);
  const [checking, setChecking] = useState(false);
  const [marketError, setMarketError] = useState("");

  const [item, setItem] = useState("Dell XPS 15");
  const [maxPrice, setMaxPrice] = useState("800");
  const [currency, setCurrency] = useState<Currency>("USD");
  const [mustHaves, setMustHaves] = useState("16GB RAM");
  const [variant, setVariant] = useState("");
  const [altVariants, setAltVariants] = useState("");
  const [extras, setExtras] = useState<Record<string, string>>({}); // key -> value you give it. Not in the map = you do not count it.
  const [address, setAddress] = useState("");
  const [phone, setPhone] = useState("");
  const [rows, setRows] = useState<VendorRow[]>(() => SAMPLE.map((s) => ({ ...s, key: newKey() })));

  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);

  async function fillFromChat() {
    if (!chat.trim()) return;
    setParsing(true);
    setNotice("");
    const { data, source } = await parseRequest(chat);
    setUsedMock(source === "mock");
    if (data.item) setItem(data.item); // keep what is there when the sentence has no item
    if (data.variant) setVariant(data.variant);
    if (data.max_price) setMaxPrice(String(data.max_price));
    setCurrency(data.currency);
    if (data.must_haves.length > 0) setMustHaves(data.must_haves.join(", "));
    setNotice(data.note ?? "Form filled. Check every field and edit what is wrong.");
    setParsing(false);
  }

  async function checkMarket() {
    if (!item.trim()) return setMarketError("Write the item first.");
    setChecking(true);
    setMarketError("");
    const r = await marketPrice(item.trim(), mustHaves.split(",").map((x) => x.trim()).filter(Boolean), currency);
    setChecking(false);
    setMarket(r.data);
    if (r.error) setMarketError(r.error);
  }

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const price = Number(maxPrice);
    if (!item.trim()) return setError("Enter the item you want to buy.");
    if (!(price > 0)) return setError("Enter a maximum price above zero.");
    if (!address.trim()) return setError("Enter a delivery address. It is shared only with the vendor you choose.");
    if (rows.length === 0) return setError("Add at least one vendor.");
    if (Object.keys(findProblems(rows)).length > 0) return setError("Fix or remove the flagged vendor rows first.");

    setStarting(true);
    const { data, source } = await createDeal({
      item: item.trim(),
      max_price: price,
      currency,
      must_haves: mustHaves.split(",").map((s) => s.trim()).filter(Boolean),
      variant: variant.trim(),
      alt_variants: altVariants.split(",").map((s) => s.trim()).filter(Boolean),
      addon_values: Object.fromEntries(Object.entries(extras).map(([k, v]) => [k, Number(v)]).filter(([, v]) => Number(v) > 0)),
      address: address.trim(),
      phone: phone.trim() || undefined,
      vendors: rows.map((r) => ({
        name: r.name.trim(),
        contact: r.contact.trim(),
        channel: r.channel,
        played_by: r.played_by ?? "you",
      })),
    });
    setUsedMock(source === "mock");
    const q = data.skipped_vendors > 0 ? `?skipped=${data.skipped_vendors}` : "";
    router.push(`/deals/${data.id}${q}`);
  }

  return (
    <div className="space-y-8">
      <DemoBanner show={usedMock} />

      <section className="rounded-lg border border-border bg-surface p-4">
        <label htmlFor="chat" className="font-medium text-text-primary">
          Tell DealDesk what you want
        </label>
        <textarea
          id="chat"
          rows={2}
          value={chat}
          onChange={(e) => setChat(e.target.value)}
          className={`${inputCls} mt-2`}
        />
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <button type="button" onClick={fillFromChat} disabled={parsing} className={btnGhost}>
            {parsing ? "Reading (the model can take a moment)" : "Fill the form"}
          </button>
          {notice && <span role="status" className="text-sm text-text-secondary">{notice}</span>}
        </div>
      </section>

      <form onSubmit={start} className="space-y-8" noValidate>
        <section className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label htmlFor="item" className={label}>Item</label>
            <input id="item" value={item} onChange={(e) => setItem(e.target.value)} className={`${inputCls} mt-1`} />
          </div>
          <div>
            <label htmlFor="max" className={label}>Maximum price</label>
            <input id="max" inputMode="decimal" value={maxPrice} onChange={(e) => setMaxPrice(e.target.value)} className={`${inputCls} mt-1`} />
          </div>
          <div>
            <label htmlFor="cur" className={label}>Currency</label>
            <select id="cur" value={currency} onChange={(e) => setCurrency(e.target.value as Currency)} className={`${inputCls} mt-1`}>
              {CURRENCIES.map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div className="sm:col-span-2 rounded-2xl border border-border bg-surface shadow-card p-3">
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" onClick={checkMarket} disabled={checking} className={btnGhost}>
                {checking ? "Checking the market (about 20 seconds)" : "Check market price"}
              </button>
              <span className="text-sm text-text-secondary">
                See what this item costs before you choose a maximum. Uses a few search credits (free if searched in the last 24 hours).
              </span>
            </div>
            {marketError && <p role="alert" className="mt-2 text-sm text-warn-text">{marketError}</p>}
            {market && !market.available && <p className="mt-2 text-sm text-text-primary">{market.text}</p>}
            {market && market.available && market.low !== null && market.median !== null && market.high !== null && (
              <div className="mt-3 space-y-2 text-sm">
                <p className="text-text-primary">
                  Market price: <strong>{formatMoney(market.low, market.currency)}</strong> to <strong>{formatMoney(market.high, market.currency)}</strong>,
                  typical <strong>{formatMoney(market.median, market.currency)}</strong> ({market.confidence} confidence, {market.n_sources} sites).
                </p>
                <p className="text-text-primary">
                  A realistic maximum is between <strong>{formatMoney(market.low, market.currency)}</strong> and <strong>{formatMoney(market.median, market.currency)}</strong>.
                  Below {formatMoney(market.low, market.currency)} a deal is very unlikely.
                </p>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={btnGhost} onClick={() => setMaxPrice(String(Math.round(market.low as number)))}>
                    Use {formatMoney(market.low, market.currency)}
                  </button>
                  <button type="button" className={btnPrimary} onClick={() => setMaxPrice(String(Math.round(market.median as number)))}>
                    Use {formatMoney(market.median, market.currency)}
                  </button>
                </div>
                {Number(maxPrice) > 0 && Number(maxPrice) < market.low && (
                  <p role="status" className="text-warn-text">Your maximum is below the lowest market price, so a deal is very unlikely.</p>
                )}
                <ul className="space-y-0.5 text-xs text-text-secondary">
                  {market.sources.map((x) => (
                    <li key={x.url}>
                      <a href={x.url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">{x.title}</a>{" "}
                      {formatMoney(x.price, market.currency)}
                    </li>
                  ))}
                </ul>
                <p className="text-xs text-text-secondary">Prices come from the web and can mix model years or versions. Check the sources.</p>
              </div>
            )}
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="must" className={label}>Must-have features (separate with commas)</label>
            <input id="must" value={mustHaves} onChange={(e) => setMustHaves(e.target.value)} className={`${inputCls} mt-1`} />
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="variant" className={label}>Variant you want: color, size or storage (optional)</label>
            <input id="variant" value={variant} onChange={(e) => setVariant(e.target.value)} placeholder="black, 128GB" className={`${inputCls} mt-1`} />
            <p className="mt-1 text-xs text-text-secondary">
              Prices often differ by color or size. The agent researches this exact variant and reads the price for it. If a vendor also
              quotes other variants, you will see them.
            </p>
          </div>
          <div className="sm:col-span-2">
            <label htmlFor="alt" className={label}>Other variants you would also accept (optional, separate with commas)</label>
            <input id="alt" value={altVariants} onChange={(e) => setAltVariants(e.target.value)} placeholder="gray, 128GB" className={`${inputCls} mt-1`} />
          </div>
          <fieldset className="sm:col-span-2 rounded-md border border-border bg-surface p-3">
            <legend className="px-1 text-sm text-text-primary">Free extras you would value</legend>
            <p className="mb-2 text-xs text-text-secondary">
              Tick what you want and say what it is worth to you in {currency}. These are your own estimates. A vendor who gives them is
              compared on the price minus their value, and the agent asks for them. What you pay is always the price.
            </p>
            <ul className="grid gap-2 sm:grid-cols-2">
              {ADDONS.map((a) => {
                const on = a.key in extras;
                return (
                  <li key={a.key} className="flex items-center gap-2 text-sm">
                    <input
                      id={`addon-${a.key}`}
                      type="checkbox"
                      checked={on}
                      onChange={(e) =>
                        setExtras((x) => {
                          const next = { ...x };
                          if (e.target.checked) next[a.key] = currency === "USD" ? String(a.suggestedUsd) : "";
                          else delete next[a.key];
                          return next;
                        })
                      }
                    />
                    <label htmlFor={`addon-${a.key}`} className="flex-1 text-text-primary">{a.label}</label>
                    <input
                      aria-label={`Value of ${a.label} in ${currency}`}
                      inputMode="decimal"
                      disabled={!on}
                      value={extras[a.key] ?? ""}
                      onChange={(e) => setExtras((x) => ({ ...x, [a.key]: e.target.value }))}
                      placeholder={currency}
                      className={`${inputCls} !w-24 disabled:opacity-40`}
                    />
                  </li>
                );
              })}
            </ul>
          </fieldset>
          <div className="sm:col-span-2">
            <label htmlFor="addr" className={label}>Delivery address</label>
            <input id="addr" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="Shared only with the vendor you accept" className={`${inputCls} mt-1`} />
          </div>
          <div>
            <label htmlFor="phone" className={label}>Phone (optional)</label>
            <input id="phone" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} className={`${inputCls} mt-1`} />
          </div>
        </section>

        <section>
          <h2 className="mb-2 font-medium text-text-primary">Vendors</h2>
          <VendorTable rows={rows} onChange={setRows} />
        </section>

        {error && (
          <p role="alert" className="rounded-md bg-danger-100 px-3 py-2 text-sm text-danger-900">{error}</p>
        )}
        <button type="submit" disabled={starting} className={btnPrimary}>
          {starting ? "Starting" : "Start negotiating"}
        </button>
      </form>
    </div>
  );
}
