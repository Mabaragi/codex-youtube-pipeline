import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/cn";

export const buttonVariants = cva(
  "inline-flex min-h-11 shrink-0 items-center justify-center gap-2 rounded-md border border-transparent px-3 text-sm font-semibold transition-[background-color,border-color,color,opacity] duration-150 focus-visible:outline-none disabled:pointer-events-none disabled:opacity-45 aria-disabled:pointer-events-none aria-disabled:opacity-45 sm:min-h-9 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--accent)] text-white hover:bg-[var(--accent-strong)] active:translate-y-px",
        secondary:
          "border-[var(--line)] bg-[var(--surface-raised)] text-[var(--foreground)] hover:border-[var(--line-strong)] hover:bg-[var(--surface-muted)]",
        ghost:
          "text-[var(--muted)] hover:bg-[var(--surface-muted)] hover:text-[var(--foreground)]",
        destructive:
          "bg-[var(--danger)] text-white hover:brightness-90 active:translate-y-px",
        outline:
          "border-[var(--line-strong)] bg-transparent text-[var(--foreground)] hover:bg-[var(--surface-muted)]",
      },
      size: {
        sm: "min-h-11 px-2.5 text-xs sm:min-h-8",
        md: "min-h-11 px-3 sm:min-h-9",
        lg: "min-h-11 px-4",
        icon: "size-11 min-h-11 px-0 sm:size-9 sm:min-h-9",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export type ButtonProps = ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  };

export function Button({ asChild, className, variant, size, ...props }: ButtonProps) {
  const Component = asChild ? Slot : "button";
  return (
    <Component
      data-slot="button"
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}
