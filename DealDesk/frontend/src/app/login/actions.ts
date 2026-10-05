"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { makeToken, safeEqual, SESSION_COOKIE, SESSION_DAYS } from "@/lib/session";

export interface LoginState {
  error?: string;
}

export async function login(_prev: LoginState, formData: FormData): Promise<LoginState> {
  const email = String(formData.get("email") ?? "").trim();
  const password = String(formData.get("password") ?? "");
  const okEmail = safeEqual(email, process.env.DEMO_EMAIL ?? "");
  const okPassword = safeEqual(password, process.env.DEMO_PASSWORD ?? "");

  if (!process.env.DEMO_EMAIL || !process.env.DEMO_PASSWORD) {
    return { error: "The demo login is not configured on the server." };
  }
  if (!okEmail || !okPassword) {
    return { error: "Wrong email or password. Use the demo details shown above." };
  }

  const store = await cookies();
  store.set(SESSION_COOKIE, makeToken(), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_DAYS * 24 * 60 * 60,
  });
  redirect("/home");
}

export async function logout(): Promise<void> {
  const store = await cookies();
  store.delete(SESSION_COOKIE);
  redirect("/login");
}
