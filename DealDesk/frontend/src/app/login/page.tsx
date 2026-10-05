import { redirect } from "next/navigation";
import { hasSession } from "@/lib/session";
import LoginForm from "./LoginForm";

export const metadata = { title: "Sign in | DealDesk" };

export default async function LoginPage() {
  if (await hasSession()) redirect("/home");

  const email = process.env.DEMO_EMAIL ?? "";
  const password = process.env.DEMO_PASSWORD ?? "";

  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center px-4 py-12">
      <h1 className="text-3xl font-semibold text-accent">DealDesk</h1>
      <p className="mt-2 text-text-secondary">
        An AI agent that negotiates with vendors for you, within limits it cannot break.
      </p>

      <div className="mt-8 rounded-2xl border border-border bg-surface p-5 shadow-card">
        <h2 className="text-lg font-medium text-text-primary">Demo account</h2>
        <p className="mt-1 text-sm text-text-secondary">
          This is a demo. Use these details to sign in.
        </p>
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-text-secondary">Email</dt>
          <dd className="break-all font-mono text-text-primary">{email}</dd>
          <dt className="text-text-secondary">Password</dt>
          <dd className="font-mono text-text-primary">{password}</dd>
        </dl>
        <LoginForm email={email} password={password} />
      </div>
    </main>
  );
}
