const PALETTE = [
  "bg-sky-800 text-sky-50",
  "bg-violet-800 text-violet-50",
  "bg-rose-800 text-rose-50",
  "bg-amber-800 text-amber-50",
  "bg-emerald-800 text-emerald-50",
  "bg-fuchsia-800 text-fuchsia-50",
];

function hash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return h;
}

export function initials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** A vendor (the other side). Color comes from the name, so it stays the same. */
export function Avatar({ name, size = 40 }: { name: string; size?: number }) {
  return (
    <div
      aria-hidden="true"
      style={{ width: size, height: size, fontSize: size * 0.38 }}
      className={`flex shrink-0 items-center justify-center rounded-full font-semibold ${PALETTE[hash(name) % PALETTE.length]}`}
    >
      {initials(name)}
    </div>
  );
}

/** The DealDesk agent. A rounded square with a shield, so it never looks like a person. */
export function AgentAvatar({ size = 40 }: { size?: number }) {
  return (
    <div
      aria-hidden="true"
      style={{ width: size, height: size }}
      className="flex shrink-0 items-center justify-center rounded-xl bg-accent-800 text-accent-50"
    >
      <svg width={size * 0.55} height={size * 0.55} viewBox="0 0 24 24" fill="none">
        <path
          d="M12 3l7 3v5c0 4.5-3 8.2-7 9.5C8 19.2 5 15.5 5 11V6l7-3z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
        <path d="M9 12l2 2 4-4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </div>
  );
}

export function YouAvatar({ size = 40 }: { size?: number }) {
  return (
    <div
      aria-hidden="true"
      style={{ width: size, height: size, fontSize: size * 0.34 }}
      className="flex shrink-0 items-center justify-center rounded-full bg-owner font-semibold text-owner-text"
    >
      You
    </div>
  );
}
