import Link from "next/link";
import { AgentAvatar, Avatar, YouAvatar } from "@/components/chat/Avatar";
import MessageList from "@/components/chat/MessageList";
import type { ChatMessage } from "@/components/chat/types";
import { btnGhost, btnPrimary, Chip } from "@/components/ui";
import { groups, items } from "@/lib/planned";

export const metadata = { title: "Home | DealDesk" };

const steps = [
  "You say what you want.",
  "DealDesk contacts people and researches real prices.",
  "Your limits are enforced by code.",
  "You decide and DealDesk finishes the deal.",
];

const roles = [
  {
    avatar: <YouAvatar size={44} />,
    title: "You",
    text: "Set the item and the most you will pay. You accept, counter or reject. Only you can accept a deal.",
  },
  {
    avatar: <AgentAvatar size={44} />,
    title: "DealDesk agent",
    text: "Writes to every vendor for you and checks the market price. It follows your limits and never accepts a deal.",
  },
  {
    avatar: <Avatar name="Vendors" size={44} />,
    title: "Vendors",
    text: "The sellers on your list. They see only what your agent sends. Your maximum price stays private.",
  },
];

const rules = [
  ["Limits enforced by plain code", "Every counter is checked by code, outside the AI. No message can talk it past your limit."],
  ["Private until you accept", "Your maximum price is never sent. Your address and phone go only to the vendor you choose, after you accept."],
  ["You make the final call", "The agent can recommend. Only you can accept, and going above your limit needs a clear confirmation."],
  ["Real prices, with sources", "The agent researches the market price on the web and shows the sources and how confident it is."],
];

const sample: ChatMessage[] = [
  { from: "agent", text: "Hello, I am interested in the Dell XPS 15. What is your best price?", at: "2026-10-01T10:00:00Z" },
  { from: "vendor", text: "Hi. Our price is $880.", at: "2026-10-01T10:02:00Z" },
  { from: "agent", text: "Thank you. Similar listings are around $700. Could you do $656?", at: "2026-10-01T10:04:00Z" },
  { from: "vendor", text: "We can do $696 as our final price.", at: "2026-10-01T10:10:00Z" },
];

const planned = items.filter((i) => !i.live);

export default function HomePage() {
  return (
    <div className="space-y-14">
      <section className="grid items-center gap-8 lg:grid-cols-[1.1fr_1fr]">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Chip live />
            <span className="text-sm text-text-secondary">Buying works today. More deal types are coming next.</span>
          </div>
          <h1 className="mt-4 text-3xl font-semibold leading-tight text-text-primary sm:text-4xl">
            Buy from vendors without the back and forth.
          </h1>
          <p className="mt-4 max-w-xl text-lg text-text-secondary">
            Tell DealDesk what you want and the most you will pay. Your agent contacts every vendor, checks the real
            market price and negotiates for you. You make the final call.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link href="/buy" className={`${btnPrimary} inline-block`}>
              Start a purchase
            </Link>
            <Link href="/deals/demo" className={`${btnGhost} inline-block !py-2.5`}>
              See a sample deal
            </Link>
          </div>
          <p className="mt-4 text-sm text-text-secondary">
            Planning to use it for something else?{" "}
            <a href="#roadmap" className="text-accent hover:underline">
              See what is coming next
            </a>
            .
          </p>
        </div>

        <figure className="overflow-hidden rounded-2xl border border-border bg-surface shadow-card">
          <figcaption className="flex items-center gap-3 border-b border-border bg-surface-2 px-4 py-3">
            <Avatar name="TechHub Store" size={36} />
            <span>
              <span className="block text-sm font-semibold text-text-primary">TechHub Store</span>
              <span className="block text-xs text-text-secondary">Sample conversation with a vendor</span>
            </span>
          </figcaption>
          <div className="bg-background p-4">
            <MessageList messages={sample} perspective="buyer" otherName="TechHub Store" showTime={false} />
          </div>
          <p className="border-t border-border bg-surface px-4 py-2 text-xs text-text-secondary">
            Vendor on the left. Your agent on the right. You decide at the end.
          </p>
        </figure>
      </section>

      <section aria-labelledby="who">
        <h2 id="who" className="text-xl font-semibold text-text-primary">Who is who in a deal</h2>
        <p className="mt-1 text-text-secondary">Three sides, and each one has a clear job.</p>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          {roles.map((r) => (
            <div key={r.title} className="rounded-2xl border border-border bg-surface shadow-card p-4">
              <div className="flex items-center gap-3">
                {r.avatar}
                <h3 className="font-medium text-text-primary">{r.title}</h3>
              </div>
              <p className="mt-3 text-sm text-text-secondary">{r.text}</p>
            </div>
          ))}
        </div>
      </section>

      <section aria-labelledby="how">
        <h2 id="how" className="text-xl font-semibold text-text-primary">How it works</h2>
        <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((s, idx) => (
            <li key={s} className="rounded-2xl border border-border bg-surface shadow-card p-4">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-accent-800 text-sm font-semibold text-accent-50">
                {idx + 1}
              </span>
              <p className="mt-3 text-text-primary">{s}</p>
            </li>
          ))}
        </ol>
      </section>

      <section aria-labelledby="rules">
        <h2 id="rules" className="text-xl font-semibold text-text-primary">Rules built into the engine</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {rules.map(([title, text]) => (
            <div key={title} className="rounded-2xl border border-border bg-surface shadow-card p-4">
              <h3 className="font-medium text-accent">{title}</h3>
              <p className="mt-1 text-sm text-text-secondary">{text}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="roadmap" aria-labelledby="roadmap-title" className="scroll-mt-6">
        <div className="flex flex-wrap items-center gap-3">
          <h2 id="roadmap-title" className="text-xl font-semibold text-text-primary">Coming next</h2>
          <span className="rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-xs font-medium text-text-secondary">
            Planned, not built yet
          </span>
        </div>
        <p className="mt-1 max-w-2xl text-text-secondary">
          Buying from vendors works today. These are the next deal types. They would run on the same engine, with the
          same rules. Open one to see the plan.
        </p>

        <div className="mt-5 space-y-6">
          {groups.map((g) => {
            const list = planned.filter((i) => i.group === g.name);
            if (list.length === 0) return null;
            return (
              <div key={g.name}>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-text-secondary">{g.label}</h3>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {list.map((i) => (
                    <Link
                      key={i.slug}
                      href={`/planned/${i.slug}`}
                      className="flex flex-col gap-2 rounded-xl border border-dashed border-border bg-surface p-4 hover:border-accent"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-medium text-text-primary">{i.title}</span>
                        <Chip live={false} />
                      </div>
                      <span className="text-sm text-text-secondary">{i.does}</span>
                    </Link>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
