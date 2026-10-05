"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { btnGhost, btnPrimary, inputCls } from "@/components/ui";
import { getAssistant, sendAssistant } from "@/lib/api";
import type { AssistantChat as Chat } from "@/lib/types";

/**
 * The assistant: one chat that never closes. Write "I want to buy a Dell XPS 15 under $800" and it starts a NEW purchase.
 * After a purchase is done you can write again. It asks only for what is missing, and starts nothing until you say yes.
 */
export default function AssistantChat() {
  const [chat, setChat] = useState<Chat | null>(null);
  const [offline, setOffline] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    getAssistant().then((c) => {
      if (cancelled) return;
      setChat(c);
      setOffline(c === null);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [chat?.messages.length]);

  async function send(message: string) {
    const t = message.trim();
    if (!t || busy) return;
    setBusy(true);
    setError("");
    const r = await sendAssistant(t);
    setBusy(false);
    if (r.chat) {
      setChat(r.chat);
      setText("");
    } else setError(r.error ?? "Something went wrong.");
  }

  return (
    <section aria-label="Chat with DealDesk" className="rounded-lg border border-border bg-surface p-4">
      <h2 className="font-medium text-text-primary">Chat with DealDesk</h2>
      <p className="mt-1 text-sm text-text-secondary">
        This chat never closes. Write what you want to buy, for example <em>I want to buy a Dell XPS 15 under $800</em>. When you ask for
        something new, it starts a new purchase with the same vendors and delivery address as your last one, after you say yes.
      </p>

      {offline ? (
        <p className="mt-3 text-sm text-text-secondary">The assistant needs the connected backend, which is not reachable now. You can still use the form below.</p>
      ) : (
        <>
          <div className="mt-3 max-h-72 min-h-24 space-y-2 overflow-y-auto rounded-md border border-border bg-background p-3" aria-live="polite">
            {(chat?.messages ?? []).length === 0 && <p className="text-sm text-text-secondary">No messages yet. Say hello, or tell me what you want to buy.</p>}
            {(chat?.messages ?? []).map((m, i) => (
              <div key={i} className={`flex ${m.sender === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] rounded-xl px-3 py-1.5 text-sm ${m.sender === "user" ? "bg-owner text-owner-text" : "bg-surface-2 text-text-primary"}`}>
                  <span className="whitespace-pre-wrap break-words">{m.text}</span>
                  {m.deal_id && (
                    <div className="mt-1">
                      <Link href={`/deals/${m.deal_id}`} className="text-accent hover:underline">
                        Open this purchase
                      </Link>
                    </div>
                  )}
                </div>
              </div>
            ))}
            <div ref={endRef} />
          </div>

          {chat?.awaiting === "confirm" && (
            <div className="mt-2 flex gap-2">
              <button type="button" disabled={busy} className={btnPrimary} onClick={() => send("yes")}>
                Yes, start
              </button>
              <button type="button" disabled={busy} className={btnGhost} onClick={() => send("no")}>
                No
              </button>
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(text);
            }}
            className="mt-2 flex gap-2"
          >
            <input
              aria-label="Message to DealDesk"
              value={text}
              maxLength={500}
              onChange={(e) => setText(e.target.value)}
              placeholder={chat?.awaiting === "max_price" ? "Your maximum price, for example 800" : "I want to buy ..."}
              className={inputCls}
            />
            <button type="submit" disabled={busy || !text.trim()} className={btnPrimary}>
              {busy ? "Sending" : "Send"}
            </button>
          </form>
          {error && <p role="alert" className="mt-2 text-sm text-danger-text">{error}</p>}
        </>
      )}
    </section>
  );
}
