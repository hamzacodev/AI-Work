"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { logout } from "@/app/login/actions";
import BackendStatus from "@/components/BackendStatus";
import ThemeToggle from "@/components/ThemeToggle";
import { resetEverything } from "@/lib/api";

const icon = (d: string) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d={d} />
  </svg>
);

/** A small spinning circle, shown while the Reset button works. */
function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" opacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

const links = [
  { href: "/home", label: "Home", icon: icon("M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z") },
  { href: "/buy", label: "Buy", icon: icon("M6 6h15l-1.5 9h-12zM6 6L5 3H2M9 20a1 1 0 1 0 0-.01M18 20a1 1 0 1 0 0-.01") },
  { href: "/whatsapp", label: "WhatsApp", icon: icon("M21 12a8 8 0 0 1-11.7 7.1L3 21l1.9-6.2A8 8 0 1 1 21 12z") },
  { href: "/scorecard", label: "Scorecard", icon: icon("M4 20V10M10 20V4M16 20v-7M22 20H2") },
];

/**
 * The app navigation. A card-style sidebar on a large screen (like a dashboard), and a top bar on a phone.
 * The theme button and the connection status sit at the top right of the page (see AppTopBar in the layout).
 */
export default function NavBar() {
  const pathname = usePathname();
  const router = useRouter();
  const [resetMsg, setResetMsg] = useState("");
  const [resetting, setResetting] = useState(false);

  async function reset() {
    if (resetting) return;
    setResetting(true);
    setResetMsg("");
    const r = await resetEverything();
    if (r.ok) {
      router.push("/buy");
      router.refresh();
    } else setResetMsg(r.message);
    setResetting(false);
  }

  const item = (l: (typeof links)[number], compact: boolean) => {
    const active = pathname === l.href || pathname.startsWith(l.href + "/");
    return (
      <Link
        key={l.href}
        href={l.href}
        aria-current={active ? "page" : undefined}
        className={`flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium ${
          active ? "bg-accent-900 text-accent-100" : "text-text-secondary hover:bg-surface-2 hover:text-text-primary"
        } ${compact ? "" : "w-full"}`}
      >
        <span className={active ? "text-accent" : ""}>{l.icon}</span>
        {l.label}
      </Link>
    );
  };

  return (
    <>
      {/* Phone and tablet: a top bar */}
      <header className="border-b border-border bg-surface lg:hidden">
        <nav className="mx-auto flex max-w-5xl flex-wrap items-center gap-1 px-4 py-3">
          <Link href="/home" className="mr-3 text-lg font-semibold text-accent">DealDesk</Link>
          {links.map((l) => item(l, true))}
          <div className="ml-auto flex items-center gap-2">
            <BackendStatus />
            <ThemeToggle />
          </div>
        </nav>
        <div className="flex items-center gap-2 px-4 pb-3">
          <button
            type="button"
            onClick={reset}
            disabled={resetting}
            aria-busy={resetting}
            className="flex items-center gap-1.5 rounded-full border border-border px-3 py-1 text-xs text-text-secondary disabled:opacity-70"
          >
            {resetting && <Spinner />}
            {resetting ? "Resetting" : "Reset all (test)"}
          </button>
          <form action={logout}>
            <button type="submit" className="rounded-full px-3 py-1 text-xs text-text-secondary">Log out</button>
          </form>
          {resetMsg && <span role="alert" className="text-xs text-warn-text">{resetMsg}</span>}
        </div>
      </header>

      {/* Large screen: a sidebar card */}
      <aside className="hidden w-64 shrink-0 p-4 lg:block">
        <div className="sticky top-4 flex h-[calc(100dvh-2rem)] flex-col rounded-2xl border border-border bg-surface p-4 shadow-card">
          <Link href="/home" className="flex items-center gap-2 px-2 py-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-primary text-sm font-bold text-on-primary">DD</span>
            <span className="text-xl font-semibold tracking-tight text-text-primary">DealDesk</span>
          </Link>
          <div className="my-3 border-t border-border" />
          <nav className="flex flex-col gap-1">{links.map((l) => item(l, false))}</nav>
          <div className="mt-auto space-y-2 border-t border-border pt-3">
            {resetMsg && <p role="alert" className="text-xs text-warn-text">{resetMsg}</p>}
            <button
              type="button"
              onClick={reset}
              disabled={resetting}
              aria-busy={resetting}
              title="Testing only: deletes every deal and chat, no questions asked"
              className="flex w-full items-center gap-2 rounded-xl border border-border px-3 py-2 text-left text-sm text-text-secondary hover:bg-surface-2 hover:text-text-primary disabled:opacity-70"
            >
              {resetting && <Spinner />}
              {resetting ? "Resetting, please wait" : "Reset all (test)"}
            </button>
            <form action={logout}>
              <button type="submit" className="w-full rounded-xl px-3 py-2 text-left text-sm text-text-secondary hover:bg-surface-2 hover:text-text-primary">
                Log out
              </button>
            </form>
          </div>
        </div>
      </aside>
    </>
  );
}
