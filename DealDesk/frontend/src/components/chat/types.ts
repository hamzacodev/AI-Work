export type ChatFrom = "vendor" | "agent" | "owner" | "note";

export interface ChatMessage {
  from: ChatFrom;
  text: string;
  at: string;
  simulated?: boolean;
  /** For a "note": danger (blocked) or info (why the agent did this). */
  tone?: "danger" | "info";
}

/**
 * Whose screen we are showing.
 * "buyer":  you are the buyer. The vendor is on the left, your agent and you are on the right.
 * "vendor": you are playing the vendor (WhatsApp demonstration). The buyer's agent is on the left.
 */
export type Perspective = "buyer" | "vendor";
