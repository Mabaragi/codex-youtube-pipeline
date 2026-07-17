import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

function Root({ className, ...props }: ComponentProps<"section">) {
  return <section data-slot="panel" className={cn("ops-panel", className)} {...props} />;
}

function Header({ className, ...props }: ComponentProps<"header">) {
  return (
    <header
      data-slot="panel-header"
      className={cn(
        "flex min-w-0 flex-wrap items-start justify-between gap-3 border-b px-4 py-3",
        className,
      )}
      {...props}
    />
  );
}

function HeadingGroup({ className, ...props }: ComponentProps<"div">) {
  return <div data-slot="panel-heading-group" className={cn("min-w-0", className)} {...props} />;
}

function Title({ className, ...props }: ComponentProps<"h2">) {
  return (
    <h2
      data-slot="panel-title"
      className={cn("text-sm font-semibold text-pretty", className)}
      {...props}
    />
  );
}

function Description({ className, ...props }: ComponentProps<"p">) {
  return (
    <p
      data-slot="panel-description"
      className={cn("mt-0.5 text-xs text-[var(--muted)]", className)}
      {...props}
    />
  );
}

function Actions({ className, ...props }: ComponentProps<"div">) {
  return <div data-slot="panel-actions" className={cn("flex flex-wrap gap-2", className)} {...props} />;
}

function Body({ className, ...props }: ComponentProps<"div">) {
  return <div data-slot="panel-body" className={cn("min-w-0 p-4", className)} {...props} />;
}

export const Panel = { Root, Header, HeadingGroup, Title, Description, Actions, Body };
