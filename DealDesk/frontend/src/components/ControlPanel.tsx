"use client";

import { useState } from "react";
import { btnGhost, btnPrimary } from "@/components/ui";
import { setControlMany } from "@/lib/api";
import type { Deal, PlayedBy } from "@/lib/types";

/**
 * Choose which vendors YOU play. Tick any vendors (one, two, all), then take control of them. The vendors you do not
 * tick stay with the simulator. You can also hand vendors back at any time.
 */
export default function ControlPanel({ deal, onChanged }: { deal: Deal; onChanged: () => void }) {
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const you = deal.vendors.filter((v) => v.played_by === "you").length;
  const toggle = (id: string) =>
    setPicked((p) => {
      const next = new Set(p);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  async function apply(mode: PlayedBy) {
    if (picked.size === 0 || busy) return;
    setBusy(true);
    setError("");
    const { data } = await setControlMany(deal.id, [...picked], mode);
    setBusy(false);
    if (data.status === "ok") {
      setPicked(new Set());
      onChanged();
    } else if (data.status === "error") setError(data.message);
  }

  return (
    <section aria-label="Take control of vendors" className="rounded-2xl border border-border bg-surface shadow-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="font-medium text-text-primary">Who plays which vendor?</h2>
          <p className="text-sm text-text-secondary">
            You play {you} of {deal.vendors.length} vendors. The rest are fake vendors (the simulator).
          </p>
        </div>
        <button type="button" className={btnGhost} onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? "Close" : "Choose vendors"}
        </button>
      </div>

      {open && (
        <div className="mt-3 space-y-3">
          <ul className="grid gap-2 sm:grid-cols-2">
            {deal.vendors.map((v) => (
              <li key={v.id}>
                <label className="flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm hover:bg-surface-2">
                  <input type="checkbox" checked={picked.has(v.id)} onChange={() => toggle(v.id)} aria-label={`Select ${v.name}`} />
                  <span className="min-w-0 flex-1 truncate text-text-primary">{v.name}</span>
                  <span className="text-xs text-text-secondary">{v.played_by === "you" ? "You" : "Simulator"}</span>
                </label>
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" className={btnGhost} onClick={() => setPicked(new Set(deal.vendors.map((v) => v.id)))}>
              Select all
            </button>
            <button type="button" className={btnGhost} onClick={() => setPicked(new Set())}>
              Select none
            </button>
            <span className="text-xs text-text-secondary">{picked.size} selected</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy || picked.size === 0} className={btnPrimary} onClick={() => apply("you")}>
              I play the selected vendors
            </button>
            <button type="button" disabled={busy || picked.size === 0} className={btnGhost} onClick={() => apply("simulator")}>
              Give the selected back to the simulator
            </button>
          </div>
          {error && <p role="alert" className="text-sm text-danger-text">{error}</p>}
          <p className="text-xs text-text-secondary">
            After you take control, open the chat of that vendor and type as the vendor. The agent answers you as the buyer, with the same
            safety checks as always.
          </p>
        </div>
      )}
    </section>
  );
}
