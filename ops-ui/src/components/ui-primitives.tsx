import type { ReactNode } from "react";
import { StatusBadge } from "@/components/status-badge";

type Tone = "muted" | "info" | "success" | "warning" | "danger";

export function LoadingState({
  label = "Loading...",
  className = "",
}: {
  label?: string;
  className?: string;
}) {
  return (
    <div
      aria-live="polite"
      className={`ops-panel p-4 text-sm text-slate-600 ${className}`}
      role="status"
    >
      {label}
    </div>
  );
}

export function ErrorState({
  message,
  className = "",
}: {
  message: ReactNode;
  className?: string;
}) {
  return (
    <div className={`ops-panel p-4 text-sm text-red-700 ${className}`} role="alert">
      {message}
    </div>
  );
}

export function EmptyState({
  label,
  className = "",
}: {
  label: ReactNode;
  className?: string;
}) {
  return (
    <div className={`text-sm text-slate-500 ${className}`} role="status">
      {label}
    </div>
  );
}

export function InlineNotice({
  children,
  tone = "muted",
  className = "",
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <div
      aria-live={tone === "danger" ? "assertive" : "polite"}
      className={`rounded border px-3 py-2 text-xs ${noticeToneClass(tone)} ${className}`}
      role={tone === "danger" ? "alert" : "status"}
    >
      {children}
    </div>
  );
}

export function ActionPanel({
  title,
  description,
  actions,
  children,
  className = "",
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`ops-panel p-4 ${className}`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="ops-section-title">{title}</h2>
          {description ? (
            <div className="ops-section-description">{description}</div>
          ) : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

export type MetricItem = {
  label: string;
  value: ReactNode;
  status?: string | null;
  meta?: ReactNode;
};

export function MetricStrip({
  items,
  ariaLabel,
  className = "",
}: {
  items: MetricItem[];
  ariaLabel?: string;
  className?: string;
}) {
  return (
    <section aria-label={ariaLabel} className={`ops-panel overflow-hidden ${className}`}>
      <div className="grid gap-px bg-slate-200 sm:grid-cols-2 xl:grid-cols-4">
        {items.map((item) => (
          <div className="min-w-0 bg-white p-4" key={item.label}>
            <div className="text-xs font-semibold uppercase text-slate-500">
              {item.label}
            </div>
            <div className="mt-1 flex min-w-0 items-center gap-2 text-xl font-semibold tabular-nums text-slate-950">
              {item.status ? <StatusBadge status={item.status} /> : null}
              <span className="min-w-0 truncate">{item.value}</span>
            </div>
            {item.meta ? <div className="mt-1 text-xs text-slate-500">{item.meta}</div> : null}
          </div>
        ))}
      </div>
    </section>
  );
}

function noticeToneClass(tone: Tone): string {
  if (tone === "success") {
    return "border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (tone === "warning") {
    return "border-amber-200 bg-amber-50 text-amber-900";
  }
  if (tone === "danger") {
    return "border-red-200 bg-red-50 text-red-800";
  }
  if (tone === "info") {
    return "border-teal-200 bg-teal-50 text-teal-900";
  }
  return "border-slate-200 bg-slate-50 text-slate-600";
}
