import { AlertTriangle, LoaderCircle } from "lucide-react";

export function RefreshStatus({ refreshing }: { refreshing: boolean }) {
  return (
    <div className="min-h-5 text-xs text-[var(--muted)]" role="status" aria-live="polite">
      {refreshing ? (
        <span className="inline-flex items-center gap-1.5">
          <LoaderCircle aria-hidden="true" className="size-3.5 animate-spin motion-reduce:animate-none" />
          새로 고치는 중…
        </span>
      ) : null}
    </div>
  );
}

export function ErrorNotice({ message }: { message: string }) {
  return (
    <div
      data-slot="error-notice"
      className="flex items-start gap-2 rounded-md border border-[var(--danger)] bg-[var(--danger-soft)] p-3 text-sm text-[var(--danger)]"
      role="alert"
    >
      <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <span className="break-words">{message}</span>
    </div>
  );
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="py-10 text-center">
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-1 text-xs text-[var(--muted)]">{description}</p>
    </div>
  );
}
