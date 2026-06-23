"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { FormEvent } from "react";
import { DataTable } from "@/components/data-table";
import { FilterActions, FilterInput, FilterSelect } from "@/components/filter-controls";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import {
  CODEX_MODEL_OPTIONS,
  CODEX_REASONING_EFFORT_OPTIONS,
} from "@/lib/codex-options";
import { compactId, formatDateTime } from "@/lib/format";
import { useCodexUsage, useCodexUsageByVideo } from "@/lib/queries";
import type {
  CodexUsage,
  CodexUsageByVideoFilters,
  CodexUsageFilters,
  CodexUsageVideoSummary,
} from "@/lib/types";
import {
  hrefWithQuery,
  positiveNumberFormValue,
  stringFormValue,
} from "@/lib/url-filters";

type UsagePageProps = {
  initialFilters: CodexUsageFilters;
};

const STATUS_OPTIONS = [
  { value: "", label: "All states" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
];

const SOURCE_OPTIONS = [
  { value: "", label: "All sources" },
  { value: "micro_event_extract", label: "micro_event_extract" },
  { value: "codex_runs", label: "codex_runs" },
  { value: "codex_runtime", label: "codex_runtime" },
];

const MODEL_OPTIONS = [
  { value: "", label: "All models" },
  ...CODEX_MODEL_OPTIONS,
];

const REASONING_EFFORT_OPTIONS = [
  { value: "", label: "All efforts" },
  ...CODEX_REASONING_EFFORT_OPTIONS,
];

export function UsagePage({ initialFilters }: UsagePageProps) {
  const router = useRouter();
  const { data, isLoading, error } = useCodexUsage(initialFilters);
  const byVideoFilters = usageByVideoFilters(initialFilters);
  const {
    data: byVideoData,
    isLoading: isByVideoLoading,
    error: byVideoError,
  } = useCodexUsageByVideo(byVideoFilters);

  const columns: ColumnDef<CodexUsage>[] = [
    { header: "Time", cell: ({ row }) => formatDateTime(row.original.createdAt) },
    {
      header: "Source",
      cell: ({ row }) => (
        <div>
          <div className="font-semibold">{row.original.source}</div>
          <div className="text-xs text-slate-500">{row.original.operation}</div>
        </div>
      ),
    },
    { header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    {
      header: "Model",
      cell: ({ row }) => (
        <div className="grid gap-1 text-xs">
          <span className="font-semibold">{row.original.model ?? "-"}</span>
          <span className="text-slate-500">
            {row.original.reasoningEffort ?? "-"}
          </span>
        </div>
      ),
    },
    {
      header: "Tokens",
      cell: ({ row }) => (
        <div className="grid gap-1 text-xs">
          <span className="font-semibold">
            {tokenValue(usageToken(row.original, "totalTokens"))} total
          </span>
          <span className="text-slate-500">
            in {tokenValue(usageToken(row.original, "inputTokens"))} / out{" "}
            {tokenValue(usageToken(row.original, "outputTokens"))}
          </span>
          <span className="text-slate-500">
            cached {tokenValue(usageToken(row.original, "cachedInputTokens"))} /
            reasoning {tokenValue(usageToken(row.original, "reasoningOutputTokens"))}
          </span>
        </div>
      ),
    },
    {
      header: "Context",
      cell: ({ row }) => (
        <div className="grid gap-1 text-xs text-slate-600">
          <span>video {idValue(row.original.videoId)}</span>
          <span>task {idValue(row.original.videoTaskId)}</span>
          <span>
            job {idValue(row.original.jobId)} / attempt{" "}
            {idValue(row.original.jobAttemptId)}
          </span>
          <span>window {idValue(row.original.windowIndex)}</span>
        </div>
      ),
    },
    {
      header: "Thread",
      cell: ({ row }) => (
        <div className="grid gap-1 text-xs text-slate-600">
          <span>{compactId(row.original.threadId)}</span>
          <span>{compactId(row.original.turnId)}</span>
          <span>{row.original.durationMs} ms</span>
        </div>
      ),
    },
    {
      header: "Error",
      cell: ({ row }) => (
        <div className="max-w-[260px] break-words text-xs text-slate-600">
          {row.original.errorType ?? "-"}
          {row.original.errorMessage ? `: ${row.original.errorMessage}` : ""}
        </div>
      ),
    },
  ];

  const byVideoColumns: ColumnDef<CodexUsageVideoSummary>[] = [
    {
      header: "Video",
      cell: ({ row }) => (
        <div className="grid max-w-[520px] gap-1">
          <Link className="font-semibold text-slate-900" href={`/videos/${row.original.videoId}`}>
            {row.original.title ?? `Video #${row.original.videoId}`}
          </Link>
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-500">
            <span>video #{row.original.videoId}</span>
            <span>{row.original.youtubeVideoId ?? "-"}</span>
            <span>{row.original.latestModel ?? "-"}</span>
            <span>{row.original.latestReasoningEffort ?? "-"}</span>
          </div>
        </div>
      ),
    },
    {
      header: "Runs",
      cell: ({ row }) => (
        <Link
          className="text-sm font-semibold"
          href={usageHref({ ...initialFilters, videoId: row.original.videoId })}
        >
          {row.original.runCount.toLocaleString("en")}
        </Link>
      ),
    },
    {
      header: "Tokens",
      cell: ({ row }) => (
        <div className="grid gap-1 text-xs">
          <span className="font-semibold">
            {tokenValue(row.original.totalTokens)} total
          </span>
          <span className="text-slate-500">
            in {tokenValue(row.original.inputTokens)} / out{" "}
            {tokenValue(row.original.outputTokens)}
          </span>
          <span className="text-slate-500">
            cached {tokenValue(row.original.cachedInputTokens)} / reasoning{" "}
            {tokenValue(row.original.reasoningOutputTokens)}
          </span>
        </div>
      ),
    },
    {
      header: "Latest",
      cell: ({ row }) => formatDateTime(row.original.latestCreatedAt),
    },
  ];

  return (
    <>
      <PageHeader title="Codex Usage" />
      <div className="mb-4 grid gap-2 md:grid-cols-3 xl:grid-cols-6">
        <Metric label="Runs" value={String(data?.summary.runCount ?? 0)} />
        <Metric label="Total" value={tokenValue(data?.summary.totalTokens)} />
        <Metric label="Input" value={tokenValue(data?.summary.inputTokens)} />
        <Metric label="Output" value={tokenValue(data?.summary.outputTokens)} />
        <Metric label="Cached" value={tokenValue(data?.summary.cachedInputTokens)} />
        <Metric
          label="Reasoning"
          value={tokenValue(data?.summary.reasoningOutputTokens)}
        />
      </div>
      <form
        key={JSON.stringify(initialFilters)}
        className="ops-panel mb-4 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          router.push(usageHref(formFilters(event)));
        }}
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <FilterSelect
            label="Source"
            name="source"
            defaultValue={initialFilters.source}
            options={SOURCE_OPTIONS}
          />
          <FilterSelect
            label="Status"
            name="status"
            defaultValue={initialFilters.status}
            options={STATUS_OPTIONS}
          />
          <FilterSelect
            label="Model"
            name="model"
            defaultValue={initialFilters.model}
            options={MODEL_OPTIONS}
          />
          <FilterSelect
            label="Reasoning"
            name="reasoningEffort"
            defaultValue={initialFilters.reasoningEffort}
            options={REASONING_EFFORT_OPTIONS}
          />
          <FilterSelect
            label="Limit"
            name="limit"
            defaultValue={String(initialFilters.limit ?? 50)}
            options={[
              { value: "50", label: "50 rows" },
              { value: "100", label: "100 rows" },
              { value: "200", label: "200 rows" },
            ]}
          />
          <FilterInput
            label="Video ID"
            name="videoId"
            defaultValue={initialFilters.videoId}
          />
          <FilterInput
            label="Task ID"
            name="videoTaskId"
            defaultValue={initialFilters.videoTaskId}
          />
          <FilterInput label="Job ID" name="jobId" defaultValue={initialFilters.jobId} />
        </div>
        <FilterActions resetHref="/usage" />
      </form>
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      <section className="mb-4 grid gap-2">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">By Video</h2>
            <div className="text-xs text-slate-500">
              {tokenValue(byVideoData?.summary.totalTokens)} tokens across{" "}
              {byVideoData?.items.length ?? 0} videos
            </div>
          </div>
        </div>
        {isByVideoLoading ? (
          <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div>
        ) : null}
        {byVideoError ? (
          <div className="ops-panel p-4 text-sm text-red-700">
            {String(byVideoError)}
          </div>
        ) : null}
        <DataTable columns={byVideoColumns} data={byVideoData?.items ?? []} />
      </section>
      <DataTable columns={columns} data={data?.items ?? []} />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {data?.nextCursor ? (
          <Link
            className="ops-button"
            href={usageHref({ ...initialFilters, cursor: data.nextCursor })}
          >
            Older
          </Link>
        ) : null}
        {initialFilters.cursor ? (
          <Link
            className="ops-button"
            href={usageHref({ ...initialFilters, cursor: undefined })}
          >
            Newest
          </Link>
        ) : null}
      </div>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="ops-panel p-3">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function formFilters(event: FormEvent<HTMLFormElement>): CodexUsageFilters {
  const form = new FormData(event.currentTarget);
  return {
    source: stringFormValue(form.get("source")),
    status: statusValue(form.get("status")),
    model: stringFormValue(form.get("model")),
    reasoningEffort: reasoningEffortValue(form.get("reasoningEffort")),
    videoId: positiveNumberFormValue(form.get("videoId")),
    videoTaskId: positiveNumberFormValue(form.get("videoTaskId")),
    jobId: positiveNumberFormValue(form.get("jobId")),
    limit: positiveNumberFormValue(form.get("limit")) ?? 50,
  };
}

function statusValue(
  value: FormDataEntryValue | null,
): CodexUsageFilters["status"] | undefined {
  const text = stringFormValue(value);
  return text === "succeeded" || text === "failed" ? text : undefined;
}

function reasoningEffortValue(
  value: FormDataEntryValue | null,
): CodexUsageFilters["reasoningEffort"] | undefined {
  const text = stringFormValue(value);
  return text === "low" || text === "medium" || text === "high" || text === "xhigh"
    ? text
    : undefined;
}

function usageHref(filters: CodexUsageFilters): string {
  return hrefWithQuery("/usage", filters);
}

function usageByVideoFilters(filters: CodexUsageFilters): CodexUsageByVideoFilters {
  return {
    source: filters.source,
    status: filters.status,
    model: filters.model,
    reasoningEffort: filters.reasoningEffort,
    videoId: filters.videoId,
    videoTaskId: filters.videoTaskId,
    jobId: filters.jobId,
    limit: Math.min(filters.limit ?? 25, 100),
  };
}

function idValue(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `#${value}`;
}

function tokenValue(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : value.toLocaleString("en");
}

type UsageTokenKey =
  | "inputTokens"
  | "outputTokens"
  | "totalTokens"
  | "cachedInputTokens"
  | "reasoningOutputTokens";

const USAGE_JSON_TOKEN_KEYS: Record<UsageTokenKey, string[]> = {
  inputTokens: ["inputTokens", "input_tokens", "promptTokens", "prompt_tokens"],
  outputTokens: [
    "outputTokens",
    "output_tokens",
    "completionTokens",
    "completion_tokens",
  ],
  totalTokens: ["totalTokens", "total_tokens", "total", "tokens"],
  cachedInputTokens: [
    "cachedInputTokens",
    "cached_input_tokens",
    "cachedTokens",
    "cached_tokens",
  ],
  reasoningOutputTokens: [
    "reasoningOutputTokens",
    "reasoning_output_tokens",
    "reasoningTokens",
    "reasoning_tokens",
  ],
};

function usageToken(usage: CodexUsage, key: UsageTokenKey): number | null | undefined {
  const directValue = usage[key];
  if (directValue !== null && directValue !== undefined) {
    return directValue;
  }
  const source = usageJsonTokenSource(usage.usageJson);
  if (!source) {
    return directValue;
  }
  for (const jsonKey of USAGE_JSON_TOKEN_KEYS[key]) {
    const value = source[jsonKey];
    if (typeof value === "number" && Number.isFinite(value)) {
      return value;
    }
  }
  return directValue;
}

function usageJsonTokenSource(value: unknown): Record<string, unknown> | null {
  if (!isRecord(value)) {
    return null;
  }
  if (isRecord(value.total)) {
    return value.total;
  }
  if (isRecord(value.last)) {
    return value.last;
  }
  return value;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
