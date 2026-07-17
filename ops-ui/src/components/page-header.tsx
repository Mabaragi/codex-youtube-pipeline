import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  heading,
  description,
  actions,
}: {
  eyebrow?: string;
  heading: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header data-slot="page-header" className="flex min-w-0 flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 max-w-3xl">
        {eyebrow ? (
          <p className="mb-1 text-xs font-semibold uppercase text-[var(--accent)]">{eyebrow}</p>
        ) : null}
        <h1 className="text-2xl font-semibold text-pretty">{heading}</h1>
        <p className="mt-1 text-sm text-pretty text-[var(--muted)]">{description}</p>
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}
