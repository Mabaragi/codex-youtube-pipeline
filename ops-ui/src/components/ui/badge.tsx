import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

const badgeVariants = cva(
  "inline-flex min-h-5 max-w-full items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-semibold leading-none",
  {
    variants: {
      tone: {
        neutral: "bg-[var(--surface-muted)] text-[var(--muted)]",
        info: "bg-[var(--accent-soft)] text-[var(--accent-strong)]",
        success: "bg-[var(--success-soft)] text-[var(--success)]",
        warning: "bg-[var(--warning-soft)] text-[var(--warning)]",
        danger: "bg-[var(--danger-soft)] text-[var(--danger)]",
      },
    },
    defaultVariants: { tone: "neutral" },
  },
);

export type BadgeProps = ComponentProps<"span"> & VariantProps<typeof badgeVariants>;

export function Badge({ className, tone, ...props }: BadgeProps) {
  return (
    <span
      data-slot="status-badge"
      className={cn(badgeVariants({ tone }), className)}
      {...props}
    />
  );
}

const STATUS_TONES: Record<string, BadgeProps["tone"]> = {
  active: "success",
  running: "success",
  succeeded: "success",
  ready: "success",
  healthy: "success",
  published: "success",
  pending: "info",
  waiting: "warning",
  draining: "warning",
  acknowledged: "warning",
  partial: "warning",
  failed: "danger",
  timed_out: "danger",
  blocked: "danger",
  open: "danger",
  critical: "danger",
  identity_mismatch: "danger",
  stale_pid: "warning",
  unreadable: "warning",
  canceled: "neutral",
  stopped: "neutral",
  suppressed: "neutral",
  resolved: "success",
};

export function StatusBadge({ value }: { value: string | null | undefined }) {
  const label = value || "unknown";
  return (
    <Badge tone={STATUS_TONES[label] ?? "neutral"} translate="no">
      {label}
    </Badge>
  );
}
