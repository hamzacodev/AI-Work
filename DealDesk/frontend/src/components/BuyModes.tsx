"use client";

import { useSyncExternalStore } from "react";
import AssistantChat from "@/components/AssistantChat";
import BuyForm from "@/components/BuyForm";

type Mode = "chat" | "form";
const KEY = "dealdesk-buy-mode";

const CHOICES: { mode: Mode; title: string; text: string }[] = [
  { mode: "chat", title: "Chat", text: "Write what you want in a sentence. DealDesk asks for what is missing, and starts after your yes." },
  { mode: "form", title: "Form", text: "Fill in the item, your maximum price, the address and the vendors yourself. You press Start negotiating." },
];

/** Two ways to start a purchase. You choose one, and only that one is shown. */
const EVENT = "dealdesk-buy-mode-change";

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

function read(): Mode | null {
  try {
    const saved = window.localStorage.getItem(KEY);
    return saved === "chat" || saved === "form" ? saved : null;
  } catch {
    return null; // the choice is only a convenience
  }
}

export default function BuyModes() {
  const mode = useSyncExternalStore(subscribe, read, () => null);

  function choose(m: Mode) {
    try {
      window.localStorage.setItem(KEY, m);
    } catch {
      /* ignore */
    }
    window.dispatchEvent(new Event(EVENT));
  }

  if (mode === null) {
    return (
      <section aria-label="How do you want to start?" className="space-y-3">
        <h2 className="font-medium text-text-primary">How do you want to start?</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          {CHOICES.map((c) => (
            <button
              key={c.mode}
              type="button"
              onClick={() => choose(c.mode)}
              className="rounded-2xl border border-border bg-surface shadow-card p-5 text-left hover:border-accent hover:bg-surface-2"
            >
              <span className="block text-lg font-semibold text-text-primary">{c.title}</span>
              <span className="mt-1 block text-sm text-text-secondary">{c.text}</span>
            </button>
          ))}
        </div>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <div role="tablist" aria-label="Start with" className="inline-flex rounded-full border border-border p-0.5">
        {CHOICES.map((c) => (
          <button
            key={c.mode}
            type="button"
            role="tab"
            aria-selected={mode === c.mode}
            onClick={() => choose(c.mode)}
            className={`rounded-full px-5 py-1.5 text-sm ${mode === c.mode ? "bg-accent-800 text-accent-50" : "text-text-secondary hover:text-text-primary"}`}
          >
            {c.title}
          </button>
        ))}
      </div>
      {mode === "chat" ? <AssistantChat /> : <BuyForm />}
    </div>
  );
}
