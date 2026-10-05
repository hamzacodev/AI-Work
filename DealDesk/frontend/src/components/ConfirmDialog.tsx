"use client";

import { useEffect } from "react";
import { btnGhost, btnPrimary } from "@/components/ui";

export default function ConfirmDialog({
  message,
  onConfirm,
  onCancel,
}: {
  message: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div role="dialog" aria-modal="true" aria-label="Confirm" className="w-full max-w-sm rounded-2xl border border-border bg-surface p-5 shadow-card">
        <p className="text-text-primary">{message}</p>
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className={btnGhost} onClick={onCancel}>Cancel</button>
          <button type="button" className={btnPrimary} onClick={onConfirm} autoFocus>Continue</button>
        </div>
      </div>
    </div>
  );
}
