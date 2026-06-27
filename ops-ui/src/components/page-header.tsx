export function PageHeader({
  title,
  description,
  meta,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  meta?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="m-0 text-2xl font-semibold tracking-normal">{title}</h1>
        {description ? (
          <p className="mt-1 max-w-3xl text-sm text-slate-600">{description}</p>
        ) : null}
        {meta ? <div className="mt-2 flex flex-wrap gap-2 text-xs text-slate-500">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </header>
  );
}
