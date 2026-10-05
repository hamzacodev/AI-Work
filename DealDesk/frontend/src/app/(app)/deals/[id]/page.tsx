import Link from "next/link";
import DealView from "@/components/DealView";

export const metadata = { title: "Deal | DealDesk" };

export default async function DealPage(props: PageProps<"/deals/[id]">) {
  const { id } = await props.params;
  const sp = await props.searchParams;
  const raw = Array.isArray(sp.skipped) ? sp.skipped[0] : sp.skipped;
  const skipped = Math.max(0, Number.parseInt(raw ?? "0", 10) || 0);

  return (
    <div className="space-y-4">
      <Link href="/buy" className="text-sm text-accent hover:underline">
        New deal
      </Link>
      <DealView id={id} skipped={skipped} />
    </div>
  );
}
