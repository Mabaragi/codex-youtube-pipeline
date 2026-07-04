"use client";

type EmbedStatusBadgeProps = {
  isEmbeddable: boolean | null | undefined;
};

export function EmbedStatusBadge({ isEmbeddable }: EmbedStatusBadgeProps) {
  if (isEmbeddable === true) {
    return (
      <span className="inline-flex w-fit items-center rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-xs font-semibold text-emerald-700">
        Embeddable
      </span>
    );
  }
  if (isEmbeddable === false) {
    return (
      <span className="inline-flex w-fit items-center rounded border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-700">
        No embed
      </span>
    );
  }
  return (
    <span className="inline-flex w-fit items-center rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs font-semibold text-slate-600">
      Unknown
    </span>
  );
}
