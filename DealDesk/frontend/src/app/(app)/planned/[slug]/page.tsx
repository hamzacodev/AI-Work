import Link from "next/link";
import { notFound, redirect } from "next/navigation";
import { Chip } from "@/components/ui";
import { findItem, items } from "@/lib/planned";

export function generateStaticParams() {
  return items.filter((i) => !i.live).map((i) => ({ slug: i.slug }));
}

export async function generateMetadata(props: PageProps<"/planned/[slug]">) {
  const { slug } = await props.params;
  const item = findItem(slug);
  return { title: `${item?.title ?? "Planned"} | DealDesk` };
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <h2 className="text-sm font-medium uppercase tracking-wide text-text-secondary">{title}</h2>
      <div className="mt-2 text-text-primary">{children}</div>
    </section>
  );
}

export default async function PlannedPage(props: PageProps<"/planned/[slug]">) {
  const { slug } = await props.params;
  const item = findItem(slug);
  if (!item) notFound();
  if (item.live) redirect("/buy");

  return (
    <div className="space-y-4">
      <Link href="/home" className="text-sm text-accent hover:underline">
        Back to Home
      </Link>
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-semibold text-text-primary">{item.title}</h1>
        <span className="rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-xs font-medium text-text-secondary">
          Planned, not built yet
        </span>
      </div>

      <Section title="What it will do">{item.does}</Section>

      {item.sides && <Section title="Which side you can be">{item.sides}</Section>}
      {item.rule && <Section title="Rule enforced in code">{item.rule}</Section>}
      {item.closing && <Section title="Closing step">{item.closing}</Section>}

      <Section title="Uses the same engine as Buy">
        <ul className="flex flex-wrap gap-2">
          {item.reuses.map((r) => (
            <li key={r} className="rounded-full bg-accent-900 px-3 py-1 text-sm text-accent-100">
              {r}
            </li>
          ))}
        </ul>
      </Section>

      <Chip live={false} />
    </div>
  );
}
