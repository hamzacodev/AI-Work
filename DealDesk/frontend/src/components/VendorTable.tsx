"use client";

import { useRef, useState } from "react";
import { btnGhost, inputCls } from "@/components/ui";
import type { Channel } from "@/lib/types";
import {
  emptyRow,
  findProblems,
  MAX_VENDORS_PROCESSED,
  parseVendorFile,
  type VendorRow,
} from "@/lib/vendors";

interface Props {
  rows: VendorRow[];
  onChange: (rows: VendorRow[]) => void;
}

export default function VendorTable({ rows, onChange }: Props) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [uploadMsg, setUploadMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const problems = findProblems(rows);
  const problemCount = Object.keys(problems).length;

  function update(key: string, patch: Partial<VendorRow>) {
    onChange(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  }

  const playing = rows.filter((r) => r.played_by === "you").length;

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    try {
      const parsed = await parseVendorFile(file);
      if (parsed.length === 0) {
        setUploadMsg({ ok: false, text: "No vendor rows found in the file." });
        return;
      }
      onChange(parsed);
      setUploadMsg({ ok: true, text: `Loaded ${parsed.length} rows from ${file.name}. Fix or remove any flagged rows.` });
    } catch (err) {
      setUploadMsg({ ok: false, text: err instanceof Error ? err.message : "Could not read the file." });
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" className={btnGhost} onClick={() => onChange([...rows, emptyRow()])}>
          Add row
        </button>
        <button type="button" className={btnGhost} onClick={() => fileRef.current?.click()}>
          Upload Excel or CSV
        </button>
        <input ref={fileRef} type="file" accept=".csv,.xlsx" className="hidden" onChange={onFile} aria-label="Upload vendor file" />
        <a href="/sample-vendors.csv" download className="text-sm text-accent hover:underline">
          Download sample file
        </a>
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-border bg-surface px-3 py-2">
        <span className="text-sm text-text-primary">Which vendors do you play yourself? ({playing} of {rows.length})</span>
        <button type="button" className={btnGhost} onClick={() => onChange(rows.map((r) => ({ ...r, played_by: "you" })))}>
          I play all
        </button>
        <button type="button" className={btnGhost} onClick={() => onChange(rows.map((r) => ({ ...r, played_by: "simulator" })))}>
          Fake testers answer for all
        </button>
        <span className="w-full text-xs text-text-secondary">
          By default you play every vendor: the agent sends the first message to each one, and then waits for you to type the
          vendor&apos;s replies. Untick a vendor to let a fake tester answer for it automatically. You can change this for any vendor
          later, while the deal is running.
        </span>
      </div>
      <p className="mt-2 text-xs text-text-secondary">
        Columns: name, email or phone (optional: channel). For now every vendor is a chat; email is planned. Max 1 MB and 200 rows. The file is read in your browser.
      </p>

      {uploadMsg && (
        <p
          role="status"
          className={`mt-2 rounded-md px-3 py-2 text-sm ${
            uploadMsg.ok ? "bg-accent-900 text-accent-100" : "bg-danger-100 text-danger-900"
          }`}
        >
          {uploadMsg.text}
        </p>
      )}

      <ul className="mt-3 space-y-2">
        {rows.map((r, idx) => (
          <li
            key={r.key}
            className={`rounded-md border p-2 ${problems[r.key] ? "border-warn-text" : "border-border"} bg-surface`}
          >
            <div className="grid gap-2 sm:grid-cols-[1fr_1.2fr_7rem_auto_auto]">
              <input
                aria-label={`Vendor ${idx + 1} name`}
                placeholder="Name"
                value={r.name}
                onChange={(e) => update(r.key, { name: e.target.value })}
                className={inputCls}
              />
              <input
                aria-label={`Vendor ${idx + 1} contact`}
                placeholder="Email or phone"
                value={r.contact}
                onChange={(e) => update(r.key, { contact: e.target.value })}
                className={inputCls}
              />
              <select
                aria-label={`Vendor ${idx + 1} channel`}
                value={r.channel}
                onChange={(e) => update(r.key, { channel: e.target.value as Channel })}
                className={inputCls}
              >
                <option value="chat">chat</option>
              </select>
              <label className="flex items-center gap-2 text-sm text-text-secondary">
                <input
                  type="checkbox"
                  checked={r.played_by === "you"}
                  onChange={(e) => update(r.key, { played_by: e.target.checked ? "you" : "simulator" })}
                  aria-label={`I play vendor ${idx + 1} myself`}
                />
                I play it
              </label>
              <button
                type="button"
                className={btnGhost}
                onClick={() => onChange(rows.filter((x) => x.key !== r.key))}
                aria-label={`Remove vendor ${idx + 1}`}
              >
                Remove
              </button>
            </div>
            {problems[r.key] && (
              <p className="mt-1 text-sm text-warn-text">Row {idx + 1}: {problems[r.key]}</p>
            )}
          </li>
        ))}
        {rows.length === 0 && <li className="text-sm text-text-secondary">No vendors yet. Add a row or upload a file.</li>}
      </ul>

      <p className="mt-2 text-sm text-text-secondary">
        {rows.length} vendors{problemCount > 0 ? `, ${problemCount} need fixing` : ""}.
        {rows.length > MAX_VENDORS_PROCESSED &&
          ` Only the first ${MAX_VENDORS_PROCESSED} valid vendors are processed in a deal.`}
      </p>
    </div>
  );
}
