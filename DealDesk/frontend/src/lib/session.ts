// Demo session. The cookie holds a signed token, so it cannot be forged
// without SESSION_SECRET. This is a demo login, not real user accounts.
// Pages are protected by calling requireSession() (not middleware or proxy).

import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";

export const SESSION_COOKIE = "dealdesk_session";
export const SESSION_DAYS = 7;

function secret(): string {
  return process.env.SESSION_SECRET || `${process.env.DEMO_PASSWORD ?? ""}:dealdesk`;
}

function sign(payload: string): string {
  return createHmac("sha256", secret()).update(payload).digest("hex");
}

export function makeToken(): string {
  const exp = Date.now() + SESSION_DAYS * 24 * 60 * 60 * 1000;
  const payload = `demo.${exp}`;
  return `${payload}.${sign(payload)}`;
}

export function verifyToken(token: string | undefined): boolean {
  if (!token) return false;
  const parts = token.split(".");
  if (parts.length !== 3 || parts[0] !== "demo") return false;
  const [who, exp, sig] = parts;
  if (!(Number(exp) > Date.now())) return false;
  const expected = Buffer.from(sign(`${who}.${exp}`));
  const given = Buffer.from(sig);
  return expected.length === given.length && timingSafeEqual(expected, given);
}

/** Compares two strings without leaking length or content through timing. */
export function safeEqual(a: string, b: string): boolean {
  const ha = createHash("sha256").update(a).digest();
  const hb = createHash("sha256").update(b).digest();
  return timingSafeEqual(ha, hb);
}

export async function hasSession(): Promise<boolean> {
  const store = await cookies();
  return verifyToken(store.get(SESSION_COOKIE)?.value);
}

export async function requireSession(): Promise<void> {
  if (!(await hasSession())) redirect("/login");
}
