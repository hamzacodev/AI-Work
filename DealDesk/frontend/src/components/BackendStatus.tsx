"use client";

import { useEffect, useState } from "react";
import { checkHealth } from "@/lib/api";

type State = { connected: boolean; model?: string; provider?: string; agentEnabled?: boolean } | null;

export default function BackendStatus() {
  const [state, setState] = useState<State>(null);
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const run = () =>
      checkHealth().then((s) => {
        if (!cancelled) setState(s);
      });
    run();
    const t = setInterval(run, 30_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  // A free server goes to sleep when nobody uses it. The first request can take up to 30 seconds, so say so instead of showing nothing.
  useEffect(() => {
    if (state) return;
    const t = setTimeout(() => setSlow(true), 2500);
    return () => clearTimeout(t);
  }, [state]);

  if (!state) {
    return slow ? (
      <span role="status" className="rounded-full border border-border px-2.5 py-1 text-xs text-text-secondary">
        Waking up the server, this can take up to 30 seconds
      </span>
    ) : null;
  }

  return (
    <span
      role="status"
      title={
        !state.connected
          ? "The backend is not reachable. Pages use demo data."
          : state.agentEnabled === false
            ? "The backend is running, but the agent is off. Set AGENT_ENABLED=true in backend/.env and restart it."
            : `Model: ${state.model ?? "unknown"} (${state.provider ?? "unknown"})`
      }
      className="flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-xs text-text-secondary"
    >
      <span
        aria-hidden="true"
        className={`h-2 w-2 rounded-full ${state.connected ? "bg-accent" : "bg-warn-100"}`}
      />
      {!state.connected ? "Demo mode" : state.agentEnabled === false ? "Agent off" : `Connected, ${state.provider ?? "model"}`}
    </span>
  );
}
