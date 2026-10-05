"use client";

import { useState } from "react";
import { formatTime } from "@/lib/format";
import { inputCls } from "@/components/ui";

export interface ChatListItem {
  id: string;
  name: string;
  avatar: React.ReactNode;
  preview: string;
  at?: string;
  /** Small line under the preview, for example the offer. */
  meta?: string;
  badge?: React.ReactNode;
  urgent?: boolean;
  /** The lowest price after all the negotiation: shown with a green mark. */
  highlight?: boolean;
  tags?: string[];
}

interface Props {
  title: string;
  items: ChatListItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  filters?: { key: string; label: string }[];
  searchLabel: string;
}

export default function ChatList({ title, items, selectedId, onSelect, filters, searchLabel }: Props) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");

  const shown = items.filter((i) => {
    if (filter !== "all" && !(i.tags ?? []).includes(filter)) return false;
    return i.name.toLowerCase().includes(query.trim().toLowerCase());
  });

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="px-4 pb-2 pt-4">
        <h2 className="text-lg font-semibold text-text-primary">{title}</h2>
        <input
          type="search"
          aria-label={searchLabel}
          placeholder={searchLabel}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className={`${inputCls} mt-3 !rounded-full !py-1.5 text-sm`}
        />
        {filters && (
          <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Filter">
            {[{ key: "all", label: "All" }, ...filters].map((f) => (
              <button
                key={f.key}
                type="button"
                aria-pressed={filter === f.key}
                onClick={() => setFilter(f.key)}
                className={`rounded-full border px-3 py-1 text-xs ${
                  filter === f.key
                    ? "border-accent bg-accent-900 text-accent-100"
                    : "border-border text-text-secondary hover:bg-surface-2"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        )}
      </div>

      <ul className="min-h-0 flex-1 overflow-y-auto">
        {shown.map((i) => (
          <li key={i.id}>
            <button
              type="button"
              onClick={() => onSelect(i.id)}
              aria-current={selectedId === i.id ? "true" : undefined}
              className={`flex w-full items-center gap-3 border-b border-border px-4 py-3 text-left hover:bg-surface-2 ${
                selectedId === i.id ? "bg-surface-2" : ""
              } ${i.highlight ? "border-l-4 border-l-accent bg-accent-900/40" : ""}`}
            >
              {i.avatar}
              <span className="min-w-0 flex-1">
                <span className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-medium text-text-primary">
                    {i.name}
                    {i.highlight && (
                      <span className="ml-2 rounded-full bg-accent-800 px-2 py-0.5 text-xs font-medium text-accent-50">Lowest price</span>
                    )}
                  </span>
                  {i.at && (
                    <span suppressHydrationWarning className={`shrink-0 text-xs ${i.urgent ? "text-warn-text" : "text-text-secondary"}`}>
                      {formatTime(i.at)}
                    </span>
                  )}
                </span>
                <span className="mt-0.5 block truncate text-sm text-text-secondary">{i.preview}</span>
                {(i.meta || i.badge) && (
                  <span className="mt-1 flex items-center justify-between gap-2">
                    <span className="text-xs text-text-secondary">{i.meta}</span>
                    {i.badge}
                  </span>
                )}
              </span>
            </button>
          </li>
        ))}
        {shown.length === 0 && <li className="px-4 py-6 text-sm text-text-secondary">No chats match.</li>}
      </ul>
    </div>
  );
}
