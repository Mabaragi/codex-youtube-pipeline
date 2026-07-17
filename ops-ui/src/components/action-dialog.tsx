"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { createContext, type ReactNode, use, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface ActionDialogState {
  open: boolean;
  reason: string;
  confirmation: string;
  pending: boolean;
  error: string | null;
}

interface ActionDialogActions {
  setOpen: (open: boolean) => void;
  setReason: (value: string) => void;
  setConfirmation: (value: string) => void;
  confirm: () => Promise<void>;
}

interface ActionDialogMeta {
  heading: string;
  description: string;
  confirmLabel: string;
  confirmationValue: string | null;
  reasonRequired: boolean;
  tone: "default" | "danger";
}

interface ActionDialogContextValue {
  state: ActionDialogState;
  actions: ActionDialogActions;
  meta: ActionDialogMeta;
}

const ActionDialogContext = createContext<ActionDialogContextValue | null>(null);

function useActionDialog(): ActionDialogContextValue {
  const value = use(ActionDialogContext);
  if (!value) throw new Error("ActionDialog components require ActionDialog.Provider.");
  return value;
}

interface ProviderProps {
  children: ReactNode;
  heading: string;
  description: string;
  confirmLabel: string;
  confirmationValue?: string;
  reasonRequired?: boolean;
  tone?: "default" | "danger";
  onConfirm: (reason: string) => Promise<void>;
}

function Provider({
  children,
  heading,
  description,
  confirmLabel,
  confirmationValue,
  reasonRequired = false,
  tone = "default",
  onConfirm,
}: ProviderProps) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const value = useMemo<ActionDialogContextValue>(() => {
    async function confirm(): Promise<void> {
      const normalizedReason = reason.trim();
      if (reasonRequired && normalizedReason.length < 3) {
        setError("사유를 3자 이상 입력하세요.");
        return;
      }
      if (confirmationValue && confirmation !== confirmationValue) {
        setError(`확인 값 “${confirmationValue}”을(를) 정확히 입력하세요.`);
        return;
      }
      setPending(true);
      setError(null);
      try {
        await onConfirm(normalizedReason);
        setOpen(false);
        setReason("");
        setConfirmation("");
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "요청을 완료하지 못했습니다.");
      } finally {
        setPending(false);
      }
    }
    return {
      state: { open, reason, confirmation, pending, error },
      actions: { setOpen, setReason, setConfirmation, confirm },
      meta: {
        heading,
        description,
        confirmLabel,
        confirmationValue: confirmationValue ?? null,
        reasonRequired,
        tone,
      },
    };
  }, [confirmation, confirmationValue, description, heading, onConfirm, open, pending, reason, reasonRequired, tone, confirmLabel, error]);

  return (
    <ActionDialogContext value={value}>
      <DialogPrimitive.Root open={open} onOpenChange={pending ? undefined : setOpen}>
        {children}
      </DialogPrimitive.Root>
    </ActionDialogContext>
  );
}

function Trigger({ children }: { children: ReactNode }) {
  return <DialogPrimitive.Trigger asChild>{children}</DialogPrimitive.Trigger>;
}

function Content({ children, className }: { children: ReactNode; className?: string }) {
  const { meta, state } = useActionDialog();
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/45 backdrop-blur-[1px] data-[state=open]:animate-in data-[state=closed]:animate-out motion-reduce:animate-none" />
      <DialogPrimitive.Content
        data-slot="action-dialog"
        className={cn(
          "ops-scrollbar fixed top-1/2 left-1/2 z-50 max-h-[calc(100dvh-2rem)] w-[min(32rem,calc(100vw-2rem))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto overscroll-contain rounded-lg border bg-[var(--surface-raised)] shadow-xl",
          className,
        )}
        aria-describedby="action-dialog-description"
      >
        <header className="border-b px-5 py-4 pr-12">
          <DialogPrimitive.Title className="text-base font-semibold text-pretty">
            {meta.heading}
          </DialogPrimitive.Title>
          <DialogPrimitive.Description
            id="action-dialog-description"
            className="mt-1 text-sm text-pretty text-[var(--muted)]"
          >
            {meta.description}
          </DialogPrimitive.Description>
        </header>
        <DialogPrimitive.Close asChild>
          <Button
            aria-label="대화상자 닫기"
            className="absolute top-2.5 right-2.5"
            size="icon"
            variant="ghost"
            disabled={state.pending}
          >
            <X aria-hidden="true" />
          </Button>
        </DialogPrimitive.Close>
        <div className="grid gap-4 p-5">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

function ReasonField() {
  const { state, actions, meta } = useActionDialog();
  if (!meta.reasonRequired) return null;
  return (
    <label className="grid gap-1.5 text-sm font-medium" htmlFor="action-dialog-reason">
      작업 사유
      <textarea
        id="action-dialog-reason"
        name="operatorReason"
        value={state.reason}
        onChange={(event) => actions.setReason(event.target.value)}
        rows={3}
        maxLength={500}
        autoComplete="off"
        placeholder="작업이 필요한 이유를 입력하세요…"
        className="min-h-24 resize-y rounded-md border bg-[var(--surface)] px-3 py-2 font-normal"
        aria-invalid={Boolean(state.error && state.reason.trim().length < 3)}
      />
      <span className="text-xs font-normal text-[var(--muted)]">3–500자</span>
    </label>
  );
}

function ConfirmationField() {
  const { state, actions, meta } = useActionDialog();
  if (!meta.confirmationValue) return null;
  return (
    <label className="grid gap-1.5 text-sm font-medium" htmlFor="action-dialog-confirmation">
      확인 값
      <span className="text-xs font-normal text-[var(--muted)]">
        <code translate="no">{meta.confirmationValue}</code> 입력
      </span>
      <input
        id="action-dialog-confirmation"
        name="confirmation"
        value={state.confirmation}
        onChange={(event) => actions.setConfirmation(event.target.value)}
        autoComplete="off"
        spellCheck={false}
        className="min-h-11 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm"
      />
    </label>
  );
}

function ErrorMessage() {
  const { state } = useActionDialog();
  return (
    <div className="min-h-5 text-sm text-[var(--danger)]" role="alert" aria-live="polite">
      {state.error}
    </div>
  );
}

function Footer() {
  const { state, actions, meta } = useActionDialog();
  return (
    <footer className="flex flex-wrap justify-end gap-2 border-t pt-4">
      <DialogPrimitive.Close asChild>
        <Button disabled={state.pending}>취소</Button>
      </DialogPrimitive.Close>
      <Button
        variant={meta.tone === "danger" ? "destructive" : "primary"}
        disabled={state.pending}
        onClick={() => void actions.confirm()}
      >
        {state.pending ? "처리 중…" : meta.confirmLabel}
      </Button>
    </footer>
  );
}

export const ActionDialog = {
  Provider,
  Trigger,
  Content,
  ReasonField,
  ConfirmationField,
  ErrorMessage,
  Footer,
};
