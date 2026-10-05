import { AgentAvatar, Avatar, YouAvatar } from "./Avatar";

/** One line that says who is who in a deal conversation (buyer view). */
export default function RoleStrip({ vendorName, playedByYou = false }: { vendorName: string; playedByYou?: boolean }) {
  return (
    <div
      aria-label="Who is who"
      className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border-b border-border bg-surface px-4 py-2 text-xs text-text-secondary"
    >
      <span className="flex items-center gap-1.5">
        <Avatar name={vendorName} size={20} />
        <span><span className="text-text-primary">{vendorName}</span>, the vendor{playedByYou ? ", played by you" : ""} (left)</span>
      </span>
      <span className="flex items-center gap-1.5">
        <AgentAvatar size={20} />
        <span><span className="text-text-primary">DealDesk agent</span>, writes to the vendor for you (right)</span>
      </span>
      <span className="flex items-center gap-1.5">
        <YouAvatar size={20} />
        <span><span className="text-text-primary">You</span>, you decide (right)</span>
      </span>
    </div>
  );
}
