"use client";

import { useActionState } from "react";
import { login, type LoginState } from "./actions";

const field =
  "mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-text-primary placeholder:text-text-secondary";

export default function LoginForm({ email, password }: { email: string; password: string }) {
  const [state, action, pending] = useActionState<LoginState, FormData>(login, {});

  return (
    <form action={action} className="mt-6 space-y-4">
      <div>
        <label htmlFor="email" className="text-sm text-text-secondary">
          Email
        </label>
        <input id="email" name="email" type="email" required defaultValue={email} autoComplete="username" className={field} />
      </div>
      <div>
        <label htmlFor="password" className="text-sm text-text-secondary">
          Password
        </label>
        <input id="password" name="password" type="text" required defaultValue={password} autoComplete="current-password" className={field} />
      </div>
      {state.error && (
        <p role="alert" className="rounded-md bg-danger-100 px-3 py-2 text-sm text-danger-900">
          {state.error}
        </p>
      )}
      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-full bg-primary px-5 py-2 font-medium text-on-primary hover:bg-primary-hover disabled:opacity-60"
      >
        {pending ? "Signing in" : "Sign in"}
      </button>
    </form>
  );
}
