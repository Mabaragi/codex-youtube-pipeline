"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Eye, Play, ScrollText } from "lucide-react";
import type { ChangeEvent, FormEvent } from "react";
import { DataTable } from "@/components/data-table";
import {
  ChannelFilterSelect,
  FilterActions,
  FilterInput,
  FilterSelect,
} from "@/components/filter-controls";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import {
  useExtractAllMicroEventsMutation,
  useOpsChannels,
  useOpsVideos,
} from "@/lib/queries";
import {
  CODEX_MODEL_OPTIONS,
  CODEX_REASONING_EFFORT_OPTIONS,
  DEFAULT_CODEX_MODEL,
  DEFAULT_CODEX_REASONING_EFFORT,
} from "@/lib/codex-options";
import { compactId, formatDateTime } from "@/lib/format";
import type {
  MicroEventBatchExtractRequest,
  OpsVideo,
  OpsVideoFilters,
} from "@/lib/types";
import {
  hrefWithQuery,
  positiveNumberFormValue,
  stringFormValue,
} from "@/lib/url-filters";

type VideosPageProps = {
  initialFilters: OpsVideoFilters;
};

const VIDEO_TASK_STATUS_OPTIONS = [
  { value: "", label: "All task states" },
  { value: "succeeded", label: "Succeeded" },
  { value: "running", label: "Running" },
  { value: "failed", label: "Failed" },
  { value: "timed_out", label: "Timed out" },
  { value: "no_transcript", label: "No transcript" },
  { value: "skipped", label: "Skipped" },
  { value: "canceled", label: "Canceled" },
];

export function VideosPage({ initialFilters }: VideosPageProps) {
  const router = useRouter();
  const { data: channelsData } = useOpsChannels();
  const { data, isLoading, error } = useOpsVideos(initialFilters);
  const extractAllMicroEvents = useExtractAllMicroEventsMutation();
  const applyFormFilters = (form: HTMLFormElement | null) => {
    if (form) {
      router.push(videosHref(formFilters(form)));
    }
  };
  const applySelectFilters = (event: ChangeEvent<HTMLSelectElement>) => {
    applyFormFilters(event.currentTarget.form);
  };

  const columns: ColumnDef<OpsVideo>[] = [
    {
      header: "Video",
      cell: ({ row }) => (
        <div>
          <div className="max-w-[520px] font-semibold">{row.original.title}</div>
          <div className="text-xs text-slate-500">{compactId(row.original.youtubeVideoId)}</div>
        </div>
      ),
    },
    { header: "Channel", accessorKey: "channelName" },
    { header: "Published", cell: ({ row }) => formatDateTime(row.original.publishedAt) },
    { header: "Duration", accessorKey: "duration" },
    {
      header: "Latest Task",
      cell: ({ row }) => (
        <div className="flex flex-col gap-1">
          <StatusBadge status={row.original.latestTaskStatus} />
          <span className="text-xs text-slate-500">{row.original.latestTaskName ?? "-"}</span>
        </div>
      ),
    },
    {
      header: "Transcript",
      cell: ({ row }) => row.original.transcriptId ?? "-",
    },
    {
      header: "Action",
      cell: ({ row }) => (
        <Link className="ops-button" href={`/videos/${row.original.videoId}`}>
          <Eye size={15} />
          Details
        </Link>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Videos" />
      <MicroEventBatchPanel extractAllMicroEvents={extractAllMicroEvents} />
      <form
        key={JSON.stringify(initialFilters)}
        className="ops-panel mb-4 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          applyFormFilters(event.currentTarget);
        }}
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <ChannelFilterSelect
            channels={channelsData?.items ?? []}
            onChange={applySelectFilters}
            value={initialFilters.channelId}
          />
          <FilterInput
            label="Search"
            name="search"
            defaultValue={initialFilters.search}
            placeholder="Title or YouTube ID"
          />
          <FilterSelect
            label="Task status"
            name="taskStatus"
            defaultValue={initialFilters.taskStatus}
            onChange={applySelectFilters}
            options={VIDEO_TASK_STATUS_OPTIONS}
          />
          <FilterInput label="Limit" name="limit" defaultValue={initialFilters.limit ?? 100} />
        </div>
        <FilterActions resetHref="/videos" />
      </form>
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      <DataTable columns={columns} data={data?.items ?? []} />
      <div className="mt-2 text-xs text-slate-500">Total {data?.total ?? 0}</div>
    </>
  );
}

type ExtractAllMicroEventsMutation = ReturnType<typeof useExtractAllMicroEventsMutation>;

function MicroEventBatchPanel({
  extractAllMicroEvents,
}: {
  extractAllMicroEvents: ExtractAllMicroEventsMutation;
}) {
  const result = extractAllMicroEvents.data;
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    extractAllMicroEvents.mutate({
      limit: positiveNumberFormValue(form.get("limit")) ?? 1,
      model: codexModelFormValue(form.get("model")),
      reasoningEffort: reasoningEffortFormValue(form.get("reasoningEffort")),
      retryFailed: form.get("retryFailed") === "on",
      regenerateSucceeded: form.get("regenerateSucceeded") === "on",
    });
  };

  return (
    <section className="ops-panel mb-4 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Micro events</h2>
          <p className="mt-1 text-xs text-slate-500">
            Runs the next eligible cue-ready videos.
          </p>
        </div>
        <Link
          className="ops-button"
          href="/tasks?taskName=micro_event_extract&limit=100"
        >
          <ScrollText size={15} />
          Tasks
        </Link>
      </div>
      <form className="mt-4" onSubmit={handleSubmit}>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <label className="grid gap-1 text-xs font-medium text-slate-600">
            Batch size
            <select className="ops-input" defaultValue="1" name="limit">
              <option value="1">1 video</option>
              <option value="3">3 videos</option>
              <option value="5">5 videos</option>
            </select>
          </label>
          <label className="grid gap-1 text-xs font-medium text-slate-600">
            Model
            <select className="ops-input" defaultValue={DEFAULT_CODEX_MODEL} name="model">
              {CODEX_MODEL_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid gap-1 text-xs font-medium text-slate-600">
            Reasoning
            <select
              className="ops-input"
              defaultValue={DEFAULT_CODEX_REASONING_EFFORT}
              name="reasoningEffort"
            >
              {CODEX_REASONING_EFFORT_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 self-end text-xs font-medium text-slate-600">
            <input className="h-4 w-4" name="retryFailed" type="checkbox" />
            Retry failed
          </label>
          <label className="flex items-center gap-2 self-end text-xs font-medium text-slate-600">
            <input
              className="h-4 w-4"
              name="regenerateSucceeded"
              type="checkbox"
            />
            Regenerate succeeded
          </label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            className="ops-button ops-button-primary"
            disabled={extractAllMicroEvents.isPending}
            title={
              extractAllMicroEvents.isPending
                ? "Micro-event batch is running"
                : "Run micro-event extraction batch"
            }
            type="submit"
          >
            <Play size={15} />
            {extractAllMicroEvents.isPending ? "Running..." : "Extract batch"}
          </button>
          {extractAllMicroEvents.error ? (
            <span className="text-xs text-red-700">
              {formatUnknownError(extractAllMicroEvents.error)}
            </span>
          ) : null}
        </div>
      </form>
      {result ? (
        <div className="mt-4 border-t border-slate-200 pt-4">
          <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-4 xl:grid-cols-8">
            <Metric label="Processed" value={result.processedCount} />
            <Metric label="Succeeded" value={result.succeededCount} />
            <Metric label="Failed" value={result.failedCount} />
            <Metric label="Skipped" value={result.skippedCount} />
            <Metric label="Timed out" value={result.timedOutCount} />
            <Metric label="Scanned" value={result.scannedCount} />
            <Metric label="Satisfied" value={result.alreadySatisfiedCount} />
            <Metric label="Ineligible" value={result.ineligibleCount} />
          </div>
          {result.items.length > 0 ? (
            <div className="mt-3 grid gap-2">
              {result.items.map((item) => (
                <div
                  className="flex flex-wrap items-center gap-2 rounded border border-slate-200 px-3 py-2 text-xs"
                  key={`${item.videoId}-${item.videoTaskId ?? "none"}`}
                >
                  <Link className="font-semibold" href={`/videos/${item.videoId}`}>
                    #{item.videoId}
                  </Link>
                  <StatusBadge status={item.status} />
                  <span>{item.reason}</span>
                  <span className="text-slate-500">{compactId(item.youtubeVideoId)}</span>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="font-semibold text-slate-900">{value}</div>
      <div>{label}</div>
    </div>
  );
}

function formFilters(formElement: HTMLFormElement): OpsVideoFilters {
  const form = new FormData(formElement);
  return {
    channelId: positiveNumberFormValue(form.get("channelId")),
    search: stringFormValue(form.get("search")),
    taskStatus: stringFormValue(form.get("taskStatus")),
    limit: positiveNumberFormValue(form.get("limit")) ?? 100,
  };
}

function videosHref(filters: OpsVideoFilters): string {
  return hrefWithQuery("/videos", filters);
}

function codexModelFormValue(
  value: FormDataEntryValue | null,
): MicroEventBatchExtractRequest["model"] {
  return (
    stringFormValue(value) ?? DEFAULT_CODEX_MODEL
  ) as MicroEventBatchExtractRequest["model"];
}

function reasoningEffortFormValue(
  value: FormDataEntryValue | null,
): MicroEventBatchExtractRequest["reasoningEffort"] {
  return (
    stringFormValue(value) ?? DEFAULT_CODEX_REASONING_EFFORT
  ) as MicroEventBatchExtractRequest["reasoningEffort"];
}

function formatUnknownError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
