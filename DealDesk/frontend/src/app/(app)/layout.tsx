import BackendStatus from "@/components/BackendStatus";
import NavBar from "@/components/NavBar";
import ThemeToggle from "@/components/ThemeToggle";
import { requireSession } from "@/lib/session";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  await requireSession();
  return (
    <div className="flex min-h-screen flex-1 flex-col lg:flex-row">
      <NavBar />
      <div className="min-w-0 flex-1">
        {/* The connection status and the theme button, top right on a large screen (the phone bar has its own) */}
        <div className="hidden items-center justify-end gap-2 px-6 pt-5 lg:flex">
          <BackendStatus />
          <ThemeToggle />
        </div>
        <main className="mx-auto w-full max-w-5xl px-4 py-6 lg:px-6">{children}</main>
      </div>
    </div>
  );
}
