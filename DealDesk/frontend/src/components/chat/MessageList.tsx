import { formatTime } from "@/lib/format";
import { Ticks } from "./Ticks";
import type { ChatFrom, ChatMessage, Perspective } from "./types";

interface Props {
  messages: ChatMessage[];
  perspective: Perspective;
  /** Name shown for the vendor (buyer view) or for the buyer's agent (vendor view). */
  otherName: string;
  showTime?: boolean;
}

interface Look {
  right: boolean;
  name: string;
  bubble: string;
  label: string;
  time: string;
}

function look(from: ChatFrom, p: Perspective, otherName: string): Look {
  if (p === "buyer") {
    if (from === "vendor") {
      return { right: false, name: otherName, bubble: "bg-surface-2 text-text-primary", label: "text-accent", time: "text-text-secondary" };
    }
    if (from === "agent") {
      return { right: true, name: "DealDesk agent, for you", bubble: "bg-accent-800 text-accent-50", label: "text-accent-50", time: "text-accent-50/80" };
    }
    return { right: true, name: "You", bubble: "bg-owner text-owner-text", label: "text-owner-text/70", time: "text-owner-text/70" };
  }
  if (from === "vendor") {
    return { right: true, name: "You, playing the vendor", bubble: "bg-accent-800 text-accent-50", label: "text-accent-50", time: "text-accent-50/80" };
  }
  return { right: false, name: otherName, bubble: "bg-surface-2 text-text-primary", label: "text-accent", time: "text-text-secondary" };
}

function dayLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const yesterday = new Date(today.getTime() - 86_400_000);
  if (same(d, today)) return "Today";
  if (same(d, yesterday)) return "Yesterday";
  return d.toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
}

export default function MessageList({ messages, perspective, otherName, showTime = true }: Props) {
  const days = messages.map((m) => dayLabel(m.at));

  return (
    <ul className="space-y-1.5">
      {messages.map((m, i) => {
        const day = days[i];
        const showDay = showTime && day !== "" && (i === 0 || day !== days[i - 1]);

        if (m.from === "note") {
          return (
            <li key={i}>
              {showDay && <DayChip label={day} />}
              {m.tone === "danger" ? (
                <div role="alert" className="mx-auto my-2 max-w-[90%] rounded-lg bg-danger-100 px-3 py-1.5 text-center text-xs font-medium text-danger-900">
                  {m.text}
                </div>
              ) : m.tone === "info" ? (
                <div className="my-1 max-w-[80%] pl-2 text-xs italic text-text-secondary">{m.text}</div>
              ) : (
                <div className="mx-auto my-2 max-w-[90%] rounded-lg bg-warn-100 px-3 py-1.5 text-center text-xs text-warn-900">
                  {m.text}
                </div>
              )}
            </li>
          );
        }

        const l = look(m.from, perspective, otherName);
        const prev = messages[i - 1];
        const newSender = !prev || prev.from !== m.from || showDay;

        return (
          <li key={i}>
            {showDay && <DayChip label={day} />}
            <div className={`flex ${l.right ? "justify-end" : "justify-start"} ${newSender ? "mt-3" : ""}`}>
              <div className={`max-w-[85%] rounded-xl px-3 py-1.5 text-sm shadow-sm sm:max-w-[75%] ${l.bubble}`}>
                {newSender && (
                  <div className={`mb-0.5 text-xs font-semibold ${l.label}`}>
                    {l.name}
                    {m.simulated && <span className="ml-1.5 font-normal opacity-80">(simulated)</span>}
                  </div>
                )}
                <span className="whitespace-pre-wrap break-words">{m.text}</span>
                {showTime && (
                  <span
                    suppressHydrationWarning
                    className={`ml-2 inline-flex items-center gap-1 align-bottom text-[10px] ${l.time}`}
                  >
                    {formatTime(m.at)}
                    {l.right && <Ticks />}
                  </span>
                )}
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function DayChip({ label }: { label: string }) {
  return (
    <div className="my-2 flex justify-center">
      <span suppressHydrationWarning className="rounded-lg bg-surface px-3 py-1 text-xs text-text-secondary">
        {label}
      </span>
    </div>
  );
}
