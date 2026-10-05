import type { Channel, VendorInput } from "./types";

/** The backend processes only this many vendors per deal (MAX_VENDORS_PER_DEAL). */
export const MAX_VENDORS_PROCESSED = 10;
export const MAX_UPLOAD_ROWS = 200;
export const MAX_UPLOAD_BYTES = 1024 * 1024;

export interface VendorRow extends VendorInput {
  key: string;
}

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE = /^\+?[\d\s\-()]{7,20}$/;

let counter = 0;
export function newKey(): string {
  counter += 1;
  return `row-${Date.now()}-${counter}`;
}

export function emptyRow(): VendorRow {
  return { key: newKey(), name: "", contact: "", channel: "chat", played_by: "you" };
}

export function isValidContact(contact: string): boolean {
  const c = contact.trim();
  return EMAIL.test(c) || PHONE.test(c);
}

/** Returns a problem per row key. Rows with no problem are not in the map. */
export function findProblems(rows: VendorRow[]): Record<string, string> {
  const problems: Record<string, string> = {};
  const seen = new Set<string>();
  for (const r of rows) {
    const contact = r.contact.trim().toLowerCase();
    if (!r.name.trim()) problems[r.key] = "Missing name";
    else if (!contact) problems[r.key] = "Missing contact";
    else if (!isValidContact(r.contact)) problems[r.key] = "Invalid email or phone";
    else if (seen.has(contact)) problems[r.key] = "Duplicate contact";
    seen.add(contact);
  }
  return problems;
}

/** Email is planned, so every vendor is a chat for now (a file that says "email" is read as a chat). */
function normaliseChannel(): Channel {
  return "chat";
}

/** Turns raw sheet rows (header row first) into vendor rows. */
export function rowsFromTable(table: unknown[][]): VendorRow[] {
  if (table.length === 0) return [];
  const header = table[0].map((h) => String(h ?? "").trim().toLowerCase());
  const col = (names: string[]) => header.findIndex((h) => names.includes(h));
  const nameCol = col(["name", "vendor", "vendor name"]);
  const contactCol = col(["email", "phone", "contact"]);
  const emailCol = col(["email"]);
  const phoneCol = col(["phone"]);
  if (nameCol === -1) throw new Error('The file needs a "name" column.');
  if (contactCol === -1 && emailCol === -1 && phoneCol === -1) {
    throw new Error('The file needs an "email" or "phone" column.');
  }

  return table
    .slice(1)
    .filter((r) => r.some((c) => String(c ?? "").trim() !== ""))
    .map((r) => {
      const email = emailCol >= 0 ? String(r[emailCol] ?? "").trim() : "";
      const phone = phoneCol >= 0 ? String(r[phoneCol] ?? "").trim() : "";
      const other = contactCol >= 0 ? String(r[contactCol] ?? "").trim() : "";
      return {
        key: newKey(),
        played_by: "you" as const,
        name: String(r[nameCol] ?? "").trim(),
        contact: email || phone || other,
        channel: normaliseChannel(),
      };
    });
}

export async function parseVendorFile(file: File): Promise<VendorRow[]> {
  if (file.size > MAX_UPLOAD_BYTES) throw new Error("The file is larger than 1 MB.");
  const lower = file.name.toLowerCase();
  let table: unknown[][];

  if (lower.endsWith(".csv")) {
    const Papa = (await import("papaparse")).default;
    const text = await file.text();
    const parsed = Papa.parse<string[]>(text, { skipEmptyLines: true });
    table = parsed.data;
  } else if (lower.endsWith(".xlsx")) {
    const { readSheet } = await import("read-excel-file/browser");
    table = (await readSheet(file)) as unknown[][];
  } else {
    throw new Error("Use a .csv or .xlsx file.");
  }

  const rows = rowsFromTable(table);
  if (rows.length > MAX_UPLOAD_ROWS) {
    throw new Error(`The file has more than ${MAX_UPLOAD_ROWS} rows.`);
  }
  return rows;
}
