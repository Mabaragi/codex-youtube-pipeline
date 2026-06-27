"use client";

import type { ColumnDef } from "@tanstack/react-table";
import {
  Archive,
  Check,
  FilePlus2,
  RefreshCw,
  Save,
  X,
} from "lucide-react";
import { useMemo, useState, type FormEvent, type ReactNode } from "react";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import {
  ActionPanel,
  EmptyState,
  ErrorState,
  InlineNotice,
  LoadingState,
} from "@/components/ui-primitives";
import { compactId, formatDateTime } from "@/lib/format";
import {
  useArchivePromptVersionMutation,
  useCreatePromptVersionMutation,
  useInvalidatePromptCacheMutation,
  usePromptDetail,
  usePrompts,
  usePublishPromptVersionMutation,
  useUpdatePromptVersionMutation,
} from "@/lib/queries";
import type {
  PromptBody,
  PromptDetail,
  PromptKey,
  PromptSummary,
  PromptVersion,
  PromptVersionCreateRequest,
  PromptVersionUpdateRequest,
} from "@/lib/types";

type EditorState = {
  promptKey: PromptKey | null;
  mode: "create" | "update";
  versionId: number | null;
  versionLabel: string;
  body: string;
  sourceNote: string;
  bodyKnown: boolean;
};

type ConfirmAction = {
  type: "publish" | "archive";
  version: PromptVersion;
};

const PROMPT_LABELS: Record<PromptKey, string> = {
  micro_event_extract: "Micro event extract",
  timeline_compose: "Timeline compose",
  timeline_episode_repair: "Timeline episode repair",
};

const EMPTY_EDITOR: EditorState = {
  promptKey: null,
  mode: "create",
  versionId: null,
  versionLabel: "",
  body: "",
  sourceNote: "",
  bodyKnown: true,
};

export function PromptsPage() {
  const prompts = usePrompts();
  const [selectedKey, setSelectedKey] = useState<PromptKey | null>(null);
  const effectiveKey = selectedKey ?? prompts.data?.[0]?.key ?? null;
  const detail = usePromptDetail(effectiveKey);
  const createVersion = useCreatePromptVersionMutation();
  const updateVersion = useUpdatePromptVersionMutation();
  const publishVersion = usePublishPromptVersionMutation();
  const archiveVersion = useArchivePromptVersionMutation();
  const invalidateCache = useInvalidatePromptCacheMutation();
  const [editorState, setEditorState] = useState<EditorState>(EMPTY_EDITOR);
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);
  const [notice, setNotice] = useState<ReactNode | null>(null);

  const selectedSummary = prompts.data?.find((item) => item.key === effectiveKey);
  const active = detail.data?.active ?? selectedSummary?.active ?? null;
  const editor =
    detail.data && editorState.promptKey !== detail.data.key
      ? newDraftEditor(detail.data)
      : editorState;
  const selectedVersion =
    editor.versionId && detail.data
      ? detail.data.versions.find((version) => version.id === editor.versionId)
      : null;
  const hasActiveDatabaseVersion =
    detail.data?.versions.some((version) => version.isActive) ?? false;
  const busy =
    createVersion.isPending ||
    updateVersion.isPending ||
    publishVersion.isPending ||
    archiveVersion.isPending ||
    invalidateCache.isPending;
  const diffRows = useMemo(
    () => buildLineDiff(active?.body ?? "", editor.body),
    [active?.body, editor.body],
  );

  const promptColumns: ColumnDef<PromptSummary>[] = [
    {
      header: "Prompt",
      cell: ({ row }) => {
        const activeRow = row.original.key === effectiveKey;
        return (
          <button
            aria-current={activeRow ? "true" : undefined}
            className="grid max-w-[260px] gap-1 text-left"
            type="button"
            onClick={() => {
              setSelectedKey(row.original.key);
              setNotice(null);
              setConfirmAction(null);
            }}
          >
            <span className="font-semibold text-[color:var(--accent)]">
              {PROMPT_LABELS[row.original.key]}
            </span>
            <span className="text-xs text-slate-500" translate="no">
              {row.original.key}
            </span>
          </button>
        );
      },
    },
    {
      header: "Active",
      cell: ({ row }) => (
        <div className="grid gap-1 text-xs">
          <span className="font-semibold">{row.original.active.versionLabel}</span>
          <StatusBadge status={row.original.active.source} />
        </div>
      ),
    },
    {
      header: "Versions",
      cell: ({ row }) => row.original.versionCount,
    },
    {
      header: "SHA",
      cell: ({ row }) => (
        <span className="font-mono text-xs">
          {compactId(row.original.active.bodySha256)}
        </span>
      ),
    },
  ];

  const versionColumns: ColumnDef<PromptVersion>[] = [
    {
      header: "Version",
      cell: ({ row }) => (
        <div className="grid gap-1">
          <button
            className="w-fit text-left font-semibold text-[color:var(--accent)]"
            type="button"
            onClick={() => selectVersion(row.original)}
          >
            {row.original.versionLabel}
          </button>
          <span className="font-mono text-xs text-slate-500">
            {compactId(row.original.bodySha256)}
          </span>
        </div>
      ),
    },
    {
      header: "State",
      cell: ({ row }) => (
        <div className="grid gap-1">
          <StatusBadge status={row.original.status} />
          {row.original.isActive ? <StatusBadge status="active" /> : null}
        </div>
      ),
    },
    {
      header: "Updated",
      cell: ({ row }) => formatDateTime(row.original.updatedAt),
    },
    {
      header: "Actions",
      cell: ({ row }) => {
        const version = row.original;
        const archiveDisabled = version.isActive || version.status === "ARCHIVED" || busy;
        const publishDisabled = version.isActive || version.status === "ARCHIVED" || busy;
        return (
          <div className="flex flex-wrap gap-2">
            {version.status === "DRAFT" ? (
              <button
                className="ops-button"
                type="button"
                onClick={() => selectVersion(version)}
              >
                Edit
              </button>
            ) : null}
            <button
              className="ops-button"
              disabled={publishDisabled}
              title={
                version.isActive
                  ? "This version is already active"
                  : version.status === "ARCHIVED"
                    ? "Archived versions cannot be published"
                    : "Publish this version"
              }
              type="button"
              onClick={() => setConfirmAction({ type: "publish", version })}
            >
              <Check aria-hidden="true" size={15} />
              Publish
            </button>
            <button
              className="ops-button"
              disabled={archiveDisabled}
              title={
                version.isActive
                  ? "Active prompt versions cannot be archived"
                  : version.status === "ARCHIVED"
                    ? "This version is already archived"
                    : "Archive this version"
              }
              type="button"
              onClick={() => setConfirmAction({ type: "archive", version })}
            >
              <Archive aria-hidden="true" size={15} />
              Archive
            </button>
          </div>
        );
      },
    },
  ];

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice(null);
    if (!effectiveKey) {
      return;
    }
    if (editor.mode === "create") {
      const body: PromptVersionCreateRequest = {
        versionLabel: editor.versionLabel.trim(),
        body: editor.body,
        sourceNote: editor.sourceNote.trim() || null,
      };
      const created = await createVersion.mutateAsync({ promptKey: effectiveKey, body });
      setEditorState({
        promptKey: effectiveKey,
        mode: "update",
        versionId: created.id,
        versionLabel: created.versionLabel,
        body: editor.body,
        sourceNote: created.sourceNote ?? "",
        bodyKnown: true,
      });
      setNotice(`Created draft ${created.versionLabel}.`);
      return;
    }

    if (!editor.versionId) {
      return;
    }
    const body: PromptVersionUpdateRequest = {
      sourceNote: editor.sourceNote.trim() || null,
    };
    if (editor.body.trim()) {
      body.body = editor.body;
    }
    const updated = await updateVersion.mutateAsync({
      promptKey: effectiveKey,
      versionId: editor.versionId,
      body,
    });
    setEditorState((current) => ({
      ...current,
      sourceNote: updated.sourceNote ?? "",
      bodyKnown: Boolean(current.body.trim()),
    }));
    setNotice(`Saved draft ${updated.versionLabel}.`);
  }

  async function handleConfirmAction() {
    if (!effectiveKey || !confirmAction) {
      return;
    }
    const action = confirmAction;
    setConfirmAction(null);
    setNotice(null);
    if (action.type === "publish") {
      const published = await publishVersion.mutateAsync({
        promptKey: effectiveKey,
        versionId: action.version.id,
      });
      setNotice(`Published ${published.versionLabel}.`);
      return;
    }
    const archived = await archiveVersion.mutateAsync({
      promptKey: effectiveKey,
      versionId: action.version.id,
    });
    setNotice(`Archived ${archived.versionLabel}.`);
  }

  async function handleInvalidateCache() {
    setNotice(null);
    const result = await invalidateCache.mutateAsync(
      effectiveKey ? { promptKey: effectiveKey } : {},
    );
    setNotice(`Invalidated ${result.invalidatedCount} cached prompt entries.`);
  }

  function startNewDraft() {
    if (!detail.data) {
      setEditorState(EMPTY_EDITOR);
      return;
    }
    setEditorState(newDraftEditor(detail.data));
    setNotice(null);
  }

  function selectVersion(version: PromptVersion) {
    if (version.status === "DRAFT") {
      setEditorState({
        promptKey: effectiveKey,
        mode: "update",
        versionId: version.id,
        versionLabel: version.versionLabel,
        body: version.isActive && active ? active.body : "",
        sourceNote: version.sourceNote ?? "",
        bodyKnown: version.isActive,
      });
      setNotice(
        version.isActive
          ? null
          : "Draft body is not returned by the API. Enter body text to update the body, or save only the source note.",
      );
      return;
    }

    setEditorState({
      promptKey: effectiveKey,
      mode: "create",
      versionId: null,
      versionLabel: "",
      body: active?.body ?? "",
      sourceNote: "",
      bodyKnown: Boolean(active?.body),
    });
    setNotice(
      version.isActive
        ? "Active version body is loaded into a new draft editor."
        : "Only active prompt body is returned by the API. The editor starts from the current active body.",
    );
  }

  const canSave =
    Boolean(effectiveKey) &&
    !busy &&
    (editor.mode === "create"
      ? Boolean(editor.versionLabel.trim()) && Boolean(editor.body.trim())
      : Boolean(editor.versionId) &&
        (Boolean(editor.body.trim()) ||
          editor.sourceNote !== (selectedVersion?.sourceNote ?? "")));

  return (
    <>
      <PageHeader
        title="Prompts"
        description="Manage active prompt versions for workers and API-triggered Codex runs."
        meta={
          active ? (
            <>
              <StatusBadge status={active.source} />
              <span>{active.versionLabel}</span>
              <span className="font-mono">{compactId(active.bodySha256)}</span>
              <span>
                {selectedSummary?.versionCount ?? detail.data?.versions.length ?? 0} versions
              </span>
            </>
          ) : null
        }
        actions={
          <button
            className="ops-button"
            disabled={!effectiveKey || invalidateCache.isPending}
            type="button"
            onClick={() => void handleInvalidateCache()}
          >
            <RefreshCw aria-hidden="true" size={15} />
            Invalidate cache
          </button>
        }
      />

      {prompts.isLoading ? <LoadingState /> : null}
      {prompts.error ? <ErrorState message={String(prompts.error)} /> : null}
      {notice ? <InlineNotice className="mb-4">{notice}</InlineNotice> : null}

      <div className="grid min-w-0 gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.35fr)]">
        <section className="grid min-w-0 gap-4">
          <DataTable
            ariaLabel="Prompt keys"
            caption="Prompt keys"
            columns={promptColumns}
            data={prompts.data ?? []}
            emptyLabel="No prompts."
          />
          {active ? <ActivePromptPanel active={active} /> : null}
        </section>

        <section className="grid min-w-0 gap-4">
          {detail.isLoading ? <LoadingState label="Loading prompt..." /> : null}
          {detail.error ? <ErrorState message={String(detail.error)} /> : null}
          {detail.data ? (
            <>
              <ActionPanel
                title={PROMPT_LABELS[detail.data.key]}
                description={
                  <span translate="no">
                    {detail.data.key} / active {detail.data.active.versionLabel}
                  </span>
                }
                actions={
                  <button className="ops-button" type="button" onClick={startNewDraft}>
                    <FilePlus2 aria-hidden="true" size={15} />
                    New draft
                  </button>
                }
              >
                <DataTable
                  ariaLabel="Prompt versions"
                  caption="Prompt versions"
                  columns={versionColumns}
                  data={detail.data.versions}
                  emptyLabel="No database versions."
                />
                {hasActiveDatabaseVersion ? (
                  <InlineNotice className="mt-3" tone="info">
                    Active prompt versions cannot be archived. Publish another version
                    before archiving the current active version.
                  </InlineNotice>
                ) : (
                  <InlineNotice className="mt-3" tone="info">
                    Active prompt is currently served from fallback resources.
                  </InlineNotice>
                )}
              </ActionPanel>

              <PromptEditor
                activeBody={detail.data.active.body}
                busy={busy}
                canSave={canSave}
                editor={editor}
                onChange={setEditorState}
                onSubmit={handleSave}
              />

              <PromptDiffPanel rows={diffRows} />
            </>
          ) : prompts.data?.length === 0 ? (
            <EmptyState label="No prompt keys." />
          ) : null}
        </section>
      </div>

      {confirmAction && active ? (
        <ConfirmPromptDialog
          action={confirmAction}
          activeLabel={active.versionLabel}
          busy={busy}
          promptKey={effectiveKey}
          onCancel={() => setConfirmAction(null)}
          onConfirm={() => void handleConfirmAction()}
        />
      ) : null}
    </>
  );
}

function ActivePromptPanel({ active }: { active: PromptBody }) {
  return (
    <ActionPanel
      title="Active Body"
      description={
        <span>
          {active.versionLabel} / <span translate="no">{active.source}</span>
        </span>
      }
    >
      <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-800">
        {active.body}
      </pre>
    </ActionPanel>
  );
}

function PromptEditor({
  activeBody,
  busy,
  canSave,
  editor,
  onChange,
  onSubmit,
}: {
  activeBody: string;
  busy: boolean;
  canSave: boolean;
  editor: EditorState;
  onChange: (next: EditorState) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const updating = editor.mode === "update";
  return (
    <form className="ops-panel grid min-w-0 gap-4 p-4" onSubmit={onSubmit}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="ops-section-title">{updating ? "Edit Draft" : "New Draft"}</h2>
          <div className="ops-section-description">
            {updating
              ? "Only draft versions can be updated."
              : "Start from active body and save as a draft."}
          </div>
        </div>
        <button className="ops-button ops-button-primary" disabled={!canSave} type="submit">
          <Save aria-hidden="true" size={15} />
          {updating ? "Save draft" : "Create draft"}
        </button>
      </div>

      {!editor.bodyKnown ? (
        <InlineNotice tone="warning">
          Existing draft body is not returned by the API. Enter body text before
          saving body changes.
        </InlineNotice>
      ) : null}

      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_180px]">
        <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-600">
          Version label
          <input
            autoComplete="off"
            className="ops-input"
            disabled={updating || busy}
            maxLength={128}
            required={!updating}
            value={editor.versionLabel}
            onChange={(event) =>
              onChange({ ...editor, versionLabel: event.currentTarget.value })
            }
          />
        </label>
        <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-600">
          Body length
          <input className="ops-input" readOnly value={`${editor.body.length} chars`} />
        </label>
      </div>

      <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-600">
        Body
        <textarea
          autoComplete="off"
          className="ops-input min-h-[320px] resize-y font-mono text-xs leading-5"
          disabled={busy}
          placeholder={activeBody ? "Prompt body" : "Enter prompt body"}
          value={editor.body}
          onChange={(event) =>
            onChange({
              ...editor,
              body: event.currentTarget.value,
              bodyKnown: true,
            })
          }
        />
      </label>

      <label className="grid min-w-0 gap-1 text-xs font-semibold text-slate-600">
        Source note
        <textarea
          autoComplete="off"
          className="ops-input min-h-20 resize-y"
          disabled={busy}
          maxLength={4000}
          placeholder="Change reason"
          value={editor.sourceNote}
          onChange={(event) =>
            onChange({ ...editor, sourceNote: event.currentTarget.value })
          }
        />
      </label>
    </form>
  );
}

function PromptDiffPanel({ rows }: { rows: DiffRow[] }) {
  return (
    <ActionPanel title="Diff" description="Active body compared with the editor body.">
      <div className="overflow-hidden rounded border border-slate-200">
        <div className="grid grid-cols-2 border-b border-slate-200 bg-slate-100 text-xs font-semibold text-slate-600">
          <div className="border-r border-slate-200 px-3 py-2">Active</div>
          <div className="px-3 py-2">Editor</div>
        </div>
        <div className="max-h-[420px] overflow-auto">
          {rows.length ? (
            rows.map((row) => (
              <div
                aria-label={`${row.tone} line ${row.index + 1}`}
                className={`grid grid-cols-2 text-xs leading-5 ${diffToneClass(row.tone)}`}
                key={row.index}
              >
                <pre className="min-w-0 whitespace-pre-wrap break-words border-r border-slate-200 px-3 py-1 font-mono">
                  {row.left || " "}
                </pre>
                <pre className="min-w-0 whitespace-pre-wrap break-words px-3 py-1 font-mono">
                  {row.right || " "}
                </pre>
              </div>
            ))
          ) : (
            <div className="p-4 text-sm text-slate-500">No lines.</div>
          )}
        </div>
      </div>
    </ActionPanel>
  );
}

function ConfirmPromptDialog({
  action,
  activeLabel,
  busy,
  promptKey,
  onCancel,
  onConfirm,
}: {
  action: ConfirmAction;
  activeLabel: string;
  busy: boolean;
  promptKey: PromptKey | null;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const publishing = action.type === "publish";
  const title = publishing ? "Publish Prompt Version" : "Archive Prompt Version";
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/30 p-4">
      <div
        aria-labelledby="prompt-confirm-title"
        aria-modal="true"
        className="ops-panel grid w-full max-w-lg gap-4 p-4 shadow-lg"
        role="dialog"
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="m-0 text-base font-semibold" id="prompt-confirm-title">
              {title}
            </h2>
            <p className="mt-1 text-sm text-slate-600">
              {publishing
                ? "This version becomes active for future worker runs."
                : "Archived versions stay in history but cannot be published."}
            </p>
          </div>
          <button
            aria-label="Close dialog"
            className="ops-button"
            type="button"
            onClick={onCancel}
          >
            <X aria-hidden="true" size={15} />
          </button>
        </div>
        <div className="grid gap-2 rounded border border-slate-200 p-3 text-sm">
          <InfoRow label="Prompt" value={promptKey ?? "-"} />
          <InfoRow label="Current active" value={activeLabel} />
          <InfoRow label="Target" value={action.version.versionLabel} />
          <InfoRow label="Status" value={action.version.status} />
        </div>
        <div className="flex flex-wrap justify-end gap-2">
          <button className="ops-button" disabled={busy} type="button" onClick={onCancel}>
            Cancel
          </button>
          <button
            className={`ops-button ${publishing ? "ops-button-primary" : ""}`}
            disabled={busy}
            type="button"
            onClick={onConfirm}
          >
            {publishing ? "Publish" : "Archive"}
          </button>
        </div>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="grid grid-cols-[120px_minmax(0,1fr)] gap-3">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div className="min-w-0 break-words" translate="no">
        {value}
      </div>
    </div>
  );
}

type DiffTone = "unchanged" | "changed" | "added" | "removed";

type DiffRow = {
  index: number;
  left: string;
  right: string;
  tone: DiffTone;
};

function buildLineDiff(left: string, right: string): DiffRow[] {
  const leftLines = splitLines(left);
  const rightLines = splitLines(right);
  const max = Math.max(leftLines.length, rightLines.length);
  const rows: DiffRow[] = [];
  for (let index = 0; index < max; index += 1) {
    const leftLine = leftLines[index] ?? "";
    const rightLine = rightLines[index] ?? "";
    let tone: DiffTone = "unchanged";
    if (leftLine && !rightLine) {
      tone = "removed";
    } else if (!leftLine && rightLine) {
      tone = "added";
    } else if (leftLine !== rightLine) {
      tone = "changed";
    }
    rows.push({ index, left: leftLine, right: rightLine, tone });
  }
  return rows;
}

function splitLines(value: string) {
  return value ? value.split(/\r?\n/) : [];
}

function diffToneClass(tone: DiffTone) {
  if (tone === "added") {
    return "bg-emerald-50 text-emerald-950";
  }
  if (tone === "removed") {
    return "bg-red-50 text-red-950";
  }
  if (tone === "changed") {
    return "bg-amber-50 text-amber-950";
  }
  return "bg-white text-slate-700";
}

function newDraftEditor(detail: PromptDetail): EditorState {
  return {
    promptKey: detail.key,
    mode: "create",
    versionId: null,
    versionLabel: "",
    body: detail.active.body,
    sourceNote: "",
    bodyKnown: true,
  };
}
