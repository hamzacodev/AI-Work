"use client";

import { useSyncExternalStore } from "react";

type Theme = "light" | "dark";
const KEY = "dd-theme";

/** A round button that switches between the light and the dark theme. The choice is remembered in this browser. */
const EVENT = "dd-theme";
const subscribe = (cb: () => void) => {
  window.addEventListener(EVENT, cb);
  return () => window.removeEventListener(EVENT, cb);
};
// The script in layout.tsx sets data-theme before the first paint, so the page itself is the source of truth.
const read = (): Theme => (document.documentElement.dataset.theme === "dark" ? "dark" : "light");

export default function ThemeToggle() {
  const theme = useSyncExternalStore(subscribe, read, () => "light" as Theme);

  function toggle() {
    const next: Theme = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    window.dispatchEvent(new Event(EVENT));
    try {
      localStorage.setItem(KEY, next);
    } catch {
      /* private window: the choice just is not remembered */
    }
  }

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={theme === "dark" ? "Switch to the light theme" : "Switch to the dark theme"}
      title={theme === "dark" ? "Light theme" : "Dark theme"}
      className="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-surface text-text-secondary shadow-card hover:text-text-primary"
    >
      {theme === "dark" ? (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}
