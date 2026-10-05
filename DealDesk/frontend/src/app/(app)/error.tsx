"use client";

import { useEffect } from "react";
import { btnPrimary } from "@/components/ui";

/** Shown when a page crashes. The agent's work is stored in the database, so nothing is lost by trying again. */
export default function Error({ error, retry }: { error: Error & { digest?: string }; retry: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div role="alert" className="mx-auto max-w-md space-y-3 rounded-2xl border border-border bg-surface shadow-card p-6 text-center">
      <h1 className="text-lg font-semibold text-text-primary">Something went wrong</h1>
      <p className="text-sm text-text-secondary">
        The page could not be shown. Your deals are safe, they are stored on the server. Try again, and if it keeps happening, reload the
        page (the server may be waking up, which can take up to 30 seconds).
      </p>
      <button type="button" className={btnPrimary} onClick={() => retry()}>
        Try again
      </button>
    </div>
  );
}
