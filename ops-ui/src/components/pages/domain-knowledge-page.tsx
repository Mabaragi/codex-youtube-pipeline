"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { Archive, Plus, Save, Trash2, X } from "lucide-react";
import { useRouter } from "next/navigation";
import {
  useMemo,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { DataTable } from "@/components/data-table";
import { FilterActions, FilterInput, FilterSelect } from "@/components/filter-controls";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { formatDateTime } from "@/lib/format";
import {
  useAddDomainEntryAliasMutation,
  useAddDomainEntryStreamerMutation,
  useArchiveDomainEntryMutation,
  useCreateDomainEntryMutation,
  useDeleteDomainEntryAliasMutation,
  useDomainEntries,
  useDomainEntryTypes,
  useRemoveDomainEntryStreamerMutation,
  useStreamers,
  useUpdateDomainEntryAliasMutation,
  useUpdateDomainEntryMutation,
} from "@/lib/queries";
import type {
  DomainEntry,
  DomainEntryAliasCreateRequest,
  DomainEntryAliasUpdateRequest,
  DomainEntryCreateRequest,
  DomainEntryFilters,
  DomainEntryType,
  DomainEntryUpdateRequest,
} from "@/lib/types";
import {
  hrefWithQuery,
  positiveNumberFormValue,
  stringFormValue,
} from "@/lib/url-filters";

type DomainKnowledgePageProps = {
  initialFilters: DomainEntryFilters;
};

type AliasDraft = {
  localId: string;
  aliasId?: number;
  surfaceForm: string;
  aliasKind: DomainEntryAliasCreateRequest["aliasKind"];
  certainty: DomainEntryAliasCreateRequest["certainty"];
  applyScope: DomainEntryAliasCreateRequest["applyScope"];
  languageCode: string;
  note: string;
};

const ACTIVE_OPTIONS = [
  { value: "true", label: "Active" },
  { value: "", label: "All states" },
  { value: "false", label: "Inactive" },
];

const PROMPT_POLICY_OPTIONS: Array<{
  value: NonNullable<DomainEntryCreateRequest["promptPolicy"]>;
  label: string;
}> = [
  { value: "AUTO_ON_MATCH", label: "AUTO_ON_MATCH" },
  { value: "ALWAYS_FOR_SCOPED_STREAMER", label: "ALWAYS_FOR_SCOPED_STREAMER" },
  { value: "DISABLED", label: "DISABLED" },
];

const ALIAS_KIND_OPTIONS: Array<{
  value: NonNullable<DomainEntryAliasCreateRequest["aliasKind"]>;
  label: string;
}> = [
  { value: "ALIAS", label: "ALIAS" },
  { value: "ASR_ERROR", label: "ASR_ERROR" },
  { value: "SEARCH_ALIAS", label: "SEARCH_ALIAS" },
  { value: "NICKNAME", label: "NICKNAME" },
  { value: "WORDPLAY", label: "WORDPLAY" },
  { value: "MISSPELLING", label: "MISSPELLING" },
];

const CERTAINTY_OPTIONS: Array<{
  value: NonNullable<DomainEntryAliasCreateRequest["certainty"]>;
  label: string;
}> = [
  { value: "LOW", label: "LOW" },
  { value: "MEDIUM", label: "MEDIUM" },
  { value: "HIGH", label: "HIGH" },
];

const APPLY_SCOPE_OPTIONS: Array<{
  value: NonNullable<DomainEntryAliasCreateRequest["applyScope"]>;
  label: string;
}> = [
  { value: "NONE", label: "NONE" },
  { value: "SEARCH_ONLY", label: "SEARCH_ONLY" },
  { value: "SEARCH_AND_SUMMARY", label: "SEARCH_AND_SUMMARY" },
  { value: "DISPLAY_ALLOWED", label: "DISPLAY_ALLOWED" },
];

export function DomainKnowledgePage({ initialFilters }: DomainKnowledgePageProps) {
  const router = useRouter();
  const types = useDomainEntryTypes();
  const streamers = useStreamers();
  const entries = useDomainEntries(initialFilters);
  const createEntry = useCreateDomainEntryMutation();
  const updateEntry = useUpdateDomainEntryMutation();
  const archiveEntry = useArchiveDomainEntryMutation();
  const addAlias = useAddDomainEntryAliasMutation();
  const updateAlias = useUpdateDomainEntryAliasMutation();
  const deleteAlias = useDeleteDomainEntryAliasMutation();
  const addStreamer = useAddDomainEntryStreamerMutation();
  const removeStreamer = useRemoveDomainEntryStreamerMutation();
  const [editingEntry, setEditingEntry] = useState<DomainEntry | null>(null);
  const [typeText, setTypeText] = useState("");
  const [selectedStreamerIds, setSelectedStreamerIds] = useState<Set<number>>(
    () => new Set(),
  );
  const [aliasRows, setAliasRows] = useState<AliasDraft[]>(() => [emptyAliasDraft()]);
  const [deletedAliasIds, setDeletedAliasIds] = useState<number[]>([]);
  const [message, setMessage] = useState<string | null>(null);

  const typeOptions = useMemo(
    () => types.data?.map((type) => ({ value: type.typeId, label: type.label })) ?? [],
    [types.data],
  );

  const columns: ColumnDef<DomainEntry>[] = [
    {
      header: "Entry",
      cell: ({ row }) => (
        <div className="grid gap-1">
          <button
            className="w-fit text-left font-semibold text-[color:var(--accent)]"
            type="button"
            onClick={() => {
              beginEditEntry(row.original);
            }}
          >
            {row.original.canonicalName}
          </button>
          <span className="text-xs text-slate-500">
            {row.original.displayName ?? row.original.disambiguation ?? "-"}
          </span>
        </div>
      ),
    },
    {
      header: "Type",
      cell: ({ row }) => (
        <div className="grid gap-1 text-xs">
          <span className="font-semibold">{row.original.typeLabel}</span>
          <span className="text-slate-500">{row.original.typeKey}</span>
        </div>
      ),
    },
    {
      header: "Detail",
      cell: ({ row }) => (
        <div className="max-w-[360px] whitespace-pre-wrap text-xs text-slate-600">
          {row.original.detail ?? "-"}
        </div>
      ),
    },
    {
      header: "Scope",
      cell: ({ row }) => (
        <div className="grid gap-1 text-xs text-slate-600">
          <span>
            {row.original.streamers.length
              ? row.original.streamers
                  .map((streamer) => streamer.streamerName)
                  .join(", ")
              : "Global"}
          </span>
          <span>{row.original.aliases.length} aliases</span>
        </div>
      ),
    },
    {
      header: "Policy",
      cell: ({ row }) => (
        <div className="grid gap-1 text-xs">
          <StatusBadge status={row.original.isActive ? "active" : "inactive"} />
          <span className="text-slate-600">{row.original.promptPolicy}</span>
          <span className="text-slate-500">priority {row.original.priority}</span>
        </div>
      ),
    },
    {
      header: "Updated",
      cell: ({ row }) => formatDateTime(row.original.updatedAt),
    },
    {
      header: "Actions",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          <button
            className="ops-button"
            type="button"
            onClick={() => {
              beginEditEntry(row.original);
            }}
          >
            Edit
          </button>
          <button
            className="ops-button"
            type="button"
            disabled={!row.original.isActive || archiveEntry.isPending}
            onClick={() => void archiveSelectedEntry(row.original)}
          >
            <Archive size={15} />
            Archive
          </button>
        </div>
      ),
    },
  ];

  async function archiveSelectedEntry(entry: DomainEntry) {
    await archiveEntry.mutateAsync(entry.entryId);
    if (editingEntry?.entryId === entry.entryId) {
      beginNewEntry();
    }
    setMessage(`Archived ${entry.canonicalName}.`);
  }

  function beginEditEntry(entry: DomainEntry) {
    setEditingEntry(entry);
    setTypeText(entry.typeLabel);
    setSelectedStreamerIds(
      new Set(entry.streamers.map((streamer) => streamer.streamerId)),
    );
    setAliasRows(
      entry.aliases.length
        ? entry.aliases.map((alias) => ({
            localId: `alias-${alias.aliasId}`,
            aliasId: alias.aliasId,
            surfaceForm: alias.surfaceForm,
            aliasKind: alias.aliasKind,
            certainty: alias.certainty,
            applyScope: alias.applyScope,
            languageCode: alias.languageCode ?? "",
            note: alias.note ?? "",
          }))
        : [emptyAliasDraft()],
    );
    setDeletedAliasIds([]);
    setMessage(null);
  }

  function beginNewEntry() {
    setEditingEntry(null);
    setTypeText("");
    setSelectedStreamerIds(new Set());
    setAliasRows([emptyAliasDraft()]);
    setDeletedAliasIds([]);
    setMessage(null);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    const formData = new FormData(event.currentTarget);
    const canonicalName = stringFormValue(formData.get("canonicalName"));
    const resolvedType = typePayload(typeText, types.data ?? []);
    if (!canonicalName || !resolvedType) {
      setMessage("Name and type are required.");
      return;
    }

    if (editingEntry) {
      const body: DomainEntryUpdateRequest = {
        ...resolvedType,
        canonicalName,
        displayName: stringFormValue(formData.get("displayName")) ?? null,
        disambiguation: stringFormValue(formData.get("disambiguation")) ?? null,
        detail: stringFormValue(formData.get("detail")) ?? null,
        promptPolicy: promptPolicyValue(formData.get("promptPolicy")),
        priority: Number(formData.get("priority") ?? 50),
        isActive: formData.get("isActive") === "true",
        sourceNote: stringFormValue(formData.get("sourceNote")) ?? null,
      };
      const updated = await updateEntry.mutateAsync({
        entryId: editingEntry.entryId,
        body,
      });
      await syncStreamers(updated, selectedStreamerIds);
      await syncAliases(updated.entryId);
      beginNewEntry();
      setMessage(`Saved ${canonicalName}.`);
      return;
    }

    const body: DomainEntryCreateRequest = {
      ...resolvedType,
      canonicalName,
      displayName: stringFormValue(formData.get("displayName")),
      disambiguation: stringFormValue(formData.get("disambiguation")),
      detail: stringFormValue(formData.get("detail")),
      promptPolicy: promptPolicyValue(formData.get("promptPolicy")),
      priority: Number(formData.get("priority") ?? 50),
      isActive: formData.get("isActive") !== "false",
      sourceNote: stringFormValue(formData.get("sourceNote")),
      streamerIds: [...selectedStreamerIds].sort((left, right) => left - right),
      aliases: aliasRows
        .map(aliasCreatePayload)
        .filter((alias): alias is DomainEntryAliasCreateRequest => Boolean(alias)),
    };
    await createEntry.mutateAsync(body);
    beginNewEntry();
    setMessage(`Created ${canonicalName}.`);
  }

  async function syncStreamers(entry: DomainEntry, nextIds: Set<number>) {
    const previousIds = new Set(
      editingEntry?.streamers.map((streamer) => streamer.streamerId) ?? [],
    );
    await Promise.all(
      [...nextIds]
        .filter((streamerId) => !previousIds.has(streamerId))
        .map((streamerId) =>
          addStreamer.mutateAsync({
            entryId: entry.entryId,
            body: { streamerId },
          }),
        ),
    );
    await Promise.all(
      [...previousIds]
        .filter((streamerId) => !nextIds.has(streamerId))
        .map((streamerId) =>
          removeStreamer.mutateAsync({
            entryId: entry.entryId,
            streamerId,
          }),
        ),
    );
  }

  async function syncAliases(entryId: number) {
    await Promise.all(deletedAliasIds.map((aliasId) => deleteAlias.mutateAsync(aliasId)));
    for (const row of aliasRows) {
      const createPayload = aliasCreatePayload(row);
      if (!createPayload) {
        continue;
      }
      if (row.aliasId) {
        await updateAlias.mutateAsync({
          aliasId: row.aliasId,
          body: aliasUpdatePayload(row),
        });
      } else {
        await addAlias.mutateAsync({ entryId, body: createPayload });
      }
    }
  }

  const busy =
    createEntry.isPending ||
    updateEntry.isPending ||
    archiveEntry.isPending ||
    addAlias.isPending ||
    updateAlias.isPending ||
    deleteAlias.isPending ||
    addStreamer.isPending ||
    removeStreamer.isPending;

  return (
    <>
      <PageHeader title="Domain Knowledge" />
      <form
        key={JSON.stringify(initialFilters)}
        className="ops-panel mb-4 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          router.push(domainKnowledgeHref(formFilters(event)));
        }}
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <FilterInput
            label="Search"
            name="q"
            defaultValue={initialFilters.q}
            placeholder="Name, alias, detail"
          />
          <FilterSelect
            label="Type"
            name="typeId"
            defaultValue={initialFilters.typeId ? String(initialFilters.typeId) : ""}
            options={[{ value: "", label: "All types" }, ...stringTypeOptions(typeOptions)]}
          />
          <FilterSelect
            label="Streamer"
            name="streamerId"
            defaultValue={
              initialFilters.streamerId ? String(initialFilters.streamerId) : ""
            }
            options={[
              { value: "", label: "All scopes" },
              ...(streamers.data ?? []).map((streamer) => ({
                value: String(streamer.id),
                label: streamer.name,
              })),
            ]}
          />
          <FilterSelect
            label="State"
            name="active"
            defaultValue={activeFilterValue(initialFilters.active)}
            options={ACTIVE_OPTIONS}
          />
          <FilterSelect
            label="Limit"
            name="limit"
            defaultValue={String(initialFilters.limit ?? 200)}
            options={[
              { value: "100", label: "100 rows" },
              { value: "200", label: "200 rows" },
              { value: "500", label: "500 rows" },
            ]}
          />
        </div>
        <FilterActions resetHref="/domain-knowledge" />
      </form>

      <div className="mb-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_440px]">
        <div>
          {entries.error ? (
            <div className="ops-panel p-4 text-sm text-red-700">
              Failed to load domain entries.
            </div>
          ) : null}
          <DataTable
            columns={columns}
            data={entries.data?.items ?? []}
            emptyLabel={entries.isLoading ? "Loading entries..." : "No entries."}
          />
        </div>
        <form
          key={editingEntry?.entryId ?? "new"}
          className="ops-panel grid gap-4 p-4"
          onSubmit={(event) => void handleSubmit(event)}
        >
          <div className="flex items-center justify-between gap-2">
            <h2 className="m-0 text-base font-semibold">
              {editingEntry ? `Edit #${editingEntry.entryId}` : "New Entry"}
            </h2>
            {editingEntry ? (
              <button
                className="ops-button"
                type="button"
                onClick={() => {
                  beginNewEntry();
                }}
              >
                <X size={15} />
                New
              </button>
            ) : null}
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-1">
            <FormField label="Canonical name">
              <input
                className="ops-input"
                name="canonicalName"
                required
                defaultValue={editingEntry?.canonicalName ?? ""}
              />
            </FormField>
            <FormField label="Type">
              <input
                className="ops-input"
                list="domain-entry-type-options"
                required
                value={typeText}
                onChange={(event) => setTypeText(event.currentTarget.value)}
              />
              <datalist id="domain-entry-type-options">
                {(types.data ?? []).map((type) => (
                  <option key={type.typeId} value={type.label} />
                ))}
              </datalist>
            </FormField>
            <FormField label="Display name">
              <input
                className="ops-input"
                name="displayName"
                defaultValue={editingEntry?.displayName ?? ""}
              />
            </FormField>
            <FormField label="Disambiguation">
              <input
                className="ops-input"
                name="disambiguation"
                defaultValue={editingEntry?.disambiguation ?? ""}
              />
            </FormField>
            <FormField label="Detail">
              <textarea
                className="ops-input min-h-28 resize-y"
                name="detail"
                defaultValue={editingEntry?.detail ?? ""}
              />
            </FormField>
            <FormField label="Streamers">
              <div className="grid max-h-36 gap-2 overflow-y-auto rounded border border-slate-200 p-2">
                {(streamers.data ?? []).map((streamer) => (
                  <label
                    key={streamer.id}
                    className="flex items-center gap-2 text-xs font-medium text-slate-700"
                  >
                    <input
                      type="checkbox"
                      checked={selectedStreamerIds.has(streamer.id)}
                      onChange={(event) => {
                        const checked = event.currentTarget.checked;
                        setSelectedStreamerIds((current) => {
                          const next = new Set(current);
                          if (checked) {
                            next.add(streamer.id);
                          } else {
                            next.delete(streamer.id);
                          }
                          return next;
                        });
                      }}
                    />
                    {streamer.name}
                  </label>
                ))}
                {streamers.data?.length === 0 ? (
                  <span className="text-xs text-slate-500">No streamers.</span>
                ) : null}
              </div>
            </FormField>
            <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-3">
              <FormField label="Prompt policy">
                <select
                  className="ops-input"
                  name="promptPolicy"
                  defaultValue={editingEntry?.promptPolicy ?? "AUTO_ON_MATCH"}
                >
                  {PROMPT_POLICY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
              </FormField>
              <FormField label="Priority">
                <input
                  className="ops-input"
                  name="priority"
                  type="number"
                  min="0"
                  max="1000"
                  defaultValue={editingEntry?.priority ?? 50}
                />
              </FormField>
              <FormField label="State">
                <select
                  className="ops-input"
                  name="isActive"
                  defaultValue={String(editingEntry?.isActive ?? true)}
                >
                  <option value="true">Active</option>
                  <option value="false">Inactive</option>
                </select>
              </FormField>
            </div>
            <FormField label="Source note">
              <input
                className="ops-input"
                name="sourceNote"
                defaultValue={editingEntry?.sourceNote ?? ""}
              />
            </FormField>
          </div>

          <div className="grid gap-2">
            <div className="flex items-center justify-between">
              <h3 className="m-0 text-sm font-semibold">Aliases</h3>
              <button
                className="ops-button"
                type="button"
                onClick={() => setAliasRows((current) => [...current, emptyAliasDraft()])}
              >
                <Plus size={15} />
                Add
              </button>
            </div>
            <div className="grid gap-2">
              {aliasRows.map((row) => (
                <AliasRow
                  key={row.localId}
                  row={row}
                  onChange={(next) =>
                    setAliasRows((current) =>
                      current.map((item) =>
                        item.localId === row.localId ? next : item,
                      ),
                    )
                  }
                  onRemove={() => {
                    const aliasId = row.aliasId;
                    if (aliasId) {
                      setDeletedAliasIds((current) => [...current, aliasId]);
                    }
                    setAliasRows((current) =>
                      current.filter((item) => item.localId !== row.localId),
                    );
                  }}
                />
              ))}
            </div>
          </div>

          {message ? <div className="text-sm text-slate-600">{message}</div> : null}
          <div className="flex flex-wrap gap-2">
            <button
              className="ops-button ops-button-primary"
              type="submit"
              disabled={busy}
            >
              <Save size={15} />
              Save
            </button>
            {editingEntry ? (
              <button
                className="ops-button"
                type="button"
                onClick={() => void archiveSelectedEntry(editingEntry)}
                disabled={!editingEntry.isActive || busy}
              >
                <Archive size={15} />
                Archive
              </button>
            ) : null}
          </div>
        </form>
      </div>
    </>
  );
}

function AliasRow({
  row,
  onChange,
  onRemove,
}: {
  row: AliasDraft;
  onChange: (next: AliasDraft) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid gap-2 rounded border border-slate-200 p-2">
      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_130px]">
        <input
          className="ops-input"
          placeholder="Surface form"
          value={row.surfaceForm}
          onChange={(event) => onChange({ ...row, surfaceForm: event.target.value })}
        />
        <select
          className="ops-input"
          value={row.aliasKind}
          onChange={(event) =>
            onChange({
              ...row,
              aliasKind: event.target.value as AliasDraft["aliasKind"],
            })
          }
        >
          {ALIAS_KIND_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div className="grid gap-2 md:grid-cols-[1fr_1fr_1fr_auto]">
        <select
          className="ops-input"
          value={row.certainty}
          onChange={(event) =>
            onChange({
              ...row,
              certainty: event.target.value as AliasDraft["certainty"],
            })
          }
        >
          {CERTAINTY_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <select
          className="ops-input"
          value={row.applyScope}
          onChange={(event) =>
            onChange({
              ...row,
              applyScope: event.target.value as AliasDraft["applyScope"],
            })
          }
        >
          {APPLY_SCOPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <input
          className="ops-input"
          placeholder="Language"
          value={row.languageCode}
          onChange={(event) => onChange({ ...row, languageCode: event.target.value })}
        />
        <button className="ops-button" type="button" onClick={onRemove}>
          <Trash2 size={15} />
        </button>
      </div>
      <input
        className="ops-input"
        placeholder="Note"
        value={row.note}
        onChange={(event) => onChange({ ...row, note: event.target.value })}
      />
    </div>
  );
}

function FormField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <label className="grid gap-1 text-xs font-semibold text-slate-600">
      {label}
      {children}
    </label>
  );
}

function emptyAliasDraft(): AliasDraft {
  return {
    localId: `alias-${Math.random().toString(16).slice(2)}`,
    surfaceForm: "",
    aliasKind: "ALIAS",
    certainty: "MEDIUM",
    applyScope: "SEARCH_ONLY",
    languageCode: "",
    note: "",
  };
}

function typePayload(
  typeText: string,
  types: DomainEntryType[],
):
  | Pick<DomainEntryCreateRequest, "typeId">
  | Pick<DomainEntryCreateRequest, "typeLabel">
  | null {
  const value = typeText.trim();
  if (!value) {
    return null;
  }
  const normalized = value.toLocaleLowerCase();
  const match = types.find(
    (type) =>
      type.label.trim().toLocaleLowerCase() === normalized ||
      type.key.toLocaleLowerCase() === normalized,
  );
  return match ? { typeId: match.typeId } : { typeLabel: value };
}

function aliasCreatePayload(
  row: AliasDraft,
): DomainEntryAliasCreateRequest | undefined {
  const surfaceForm = row.surfaceForm.trim();
  if (!surfaceForm) {
    return undefined;
  }
  return {
    surfaceForm,
    aliasKind: row.aliasKind,
    certainty: row.certainty,
    applyScope: row.applyScope,
    languageCode: row.languageCode.trim() || null,
    note: row.note.trim() || null,
  };
}

function aliasUpdatePayload(row: AliasDraft): DomainEntryAliasUpdateRequest {
  return {
    surfaceForm: row.surfaceForm.trim(),
    aliasKind: row.aliasKind,
    certainty: row.certainty,
    applyScope: row.applyScope,
    languageCode: row.languageCode.trim() || null,
    note: row.note.trim() || null,
  };
}

function promptPolicyValue(
  value: FormDataEntryValue | null,
): DomainEntryCreateRequest["promptPolicy"] {
  return value === "ALWAYS_FOR_SCOPED_STREAMER" || value === "DISABLED"
    ? value
    : "AUTO_ON_MATCH";
}

function formFilters(event: FormEvent<HTMLFormElement>): DomainEntryFilters {
  const form = new FormData(event.currentTarget);
  return {
    q: stringFormValue(form.get("q")),
    typeId: positiveNumberFormValue(form.get("typeId")),
    streamerId: positiveNumberFormValue(form.get("streamerId")),
    active: activeFilter(form.get("active")),
    limit: positiveNumberFormValue(form.get("limit")) ?? 200,
  };
}

function activeFilter(value: FormDataEntryValue | null): boolean | undefined {
  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  return undefined;
}

function activeFilterValue(value: boolean | null | undefined): string {
  if (value === true) {
    return "true";
  }
  if (value === false) {
    return "false";
  }
  return "";
}

function domainKnowledgeHref(filters: DomainEntryFilters): string {
  return hrefWithQuery("/domain-knowledge", filters);
}

function stringTypeOptions(options: Array<{ value: number; label: string }>) {
  return options.map((option) => ({
    value: String(option.value),
    label: option.label,
  }));
}
