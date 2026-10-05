import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md space-y-3 p-8 text-center">
      <h1 className="text-lg font-semibold text-text-primary">Page not found</h1>
      <p className="text-sm text-text-secondary">This page does not exist. It may be a planned feature that is not built yet.</p>
      <Link href="/home" className="text-accent hover:underline">
        Go to Home
      </Link>
    </div>
  );
}
