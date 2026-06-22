"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { RotateCw, ScrollText } from "lucide-react";
import type { FormEvent } from "react";
import { DataTable } from "@/components/data-table";
import {
  ChannelFilterSelect,
  FilterActions,
  FilterSelect,
} from "@/components/filter-controls";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { TranscriptCollectionStatus } from "@/components/transcript-collection-status";
import {
  useOpsChannels,
  useOpsVideoTasks,
  useRetryJobMutation,
  useRunningTranscriptBatches,
  useRunningTranscriptTasks,
} from "@/lib/queries";
import { compactId, formatDateTime } from "@/lib/format";
import { logsHref } from "@/lib/logs";
import {
  buildTranscriptCollectionLock,
  transcriptCollectionActionTitle,
} from "@/lib/transcript-collection-lock";
import type { OpsVideoTask, OpsVideoTaskFilters } from "@/lib/types";
import {
  hrefWithQuery,
  positiveNumberFormValue,
  stringFormValue,
} from "@/lib/url-filters";

type TasksPageProps = {
  initialFilters: OpsVideoTaskFilters;
};

const TASK_STATUS_OPTIONS = [
  { value: "", label: "All task states" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "timed_out", label: "Timed out" },
  { value: "no_transcript", label: "No transcript" },
  { value: "skipped", label: "Skipped" },
  { value: "canceled", label: "Canceled" },
];

const TASK_NAME_OPTIONS = [
  { value: "", label: "All task names" },
  { value: "transcript_collect", label: "transcript_collect" },
];

export function TasksPage({ initialFilters }: TasksPageProps) {
  const router = useRouter();
  const { data: channelsData } = useOpsChannels();
  const { data, isLoading, error } = useOpsVideoTasks(initialFilters);
  const runningTranscriptTasks = useRunningTranscriptTasks();
  const runningTranscriptBatches = useRunningTranscriptBatches();
  const retryJob = useRetryJobMutation();
  const transcriptLock = buildTranscriptCollectionLock({
    runningTasks: runningTranscriptTasks.data,
    runningBatches: runningTranscriptBatches.data,
    tasksLoading: runningTranscriptTasks.isLoading,
    batchesLoading: runningTranscriptBatches.isLoading,
    tasksError: runningTranscriptTasks.isError,
    batchesError: runningTranscriptBatches.isError,
  });

  const columns: ColumnDef<OpsVideoTask>[] = [
    {
      header: "Task",
      cell: ({ row }) => (
        <div>
          <div className="font-semibold">{row.original.taskName}</div>
          <div className="text-xs text-slate-500">{row.original.taskVersion}</div>
        </div>
      ),
    },
    {
      header: "Video",
      cell: ({ row }) => (
        <div>
          <div>{compactId(row.original.youtubeVideoId)}</div>
          <div className="text-xs text-slate-500">{row.original.channelName}</div>
        </div>
      ),
    },
    { header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    { header: "Started", cell: ({ row }) => formatDateTime(row.original.startedAt) },
    { header: "Completed", cell: ({ row }) => formatDateTime(row.original.completedAt) },
    {
      header: "Error",
      cell: ({ row }) => (
        <div className="max-w-[360px] text-xs text-slate-600">
          {row.original.errorType ?? "-"}
          {row.original.errorMessage ? `: ${row.original.errorMessage}` : ""}
        </div>
      ),
    },
    {
      header: "Action",
      cell: ({ row }) => {
        const retryLocked =
          row.original.taskName === "transcript_collect" && transcriptLock.isLocked;
        return (
          <div className="flex flex-wrap gap-2">
            {row.original.jobId && ["failed", "timed_out"].includes(row.original.status) ? (
              <button
                className="ops-button"
                disabled={retryJob.isPending || retryLocked}
                onClick={() => retryJob.mutate(row.original.jobId as number)}
                title={
                  retryLocked
                    ? transcriptCollectionActionTitle(transcriptLock)
                    : "Retry job"
                }
              >
                <RotateCw size={15} />
                Retry job
              </button>
            ) : null}
            <Link
              className="ops-button"
              href={logsHref({ videoTaskId: row.original.videoTaskId })}
            >
              <ScrollText size={15} />
              Logs
            </Link>
          </div>
        );
      },
    },
  ];

  return (
    <>
      <PageHeader title="Video Tasks" />
      <TranscriptCollectionStatus className="mb-4" state={transcriptLock} />
      <form
        key={JSON.stringify(initialFilters)}
        className="ops-panel mb-4 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          router.push(tasksHref(formFilters(event)));
        }}
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <ChannelFilterSelect
            channels={channelsData?.items ?? []}
            value={initialFilters.channelId}
          />
          <FilterSelect
            label="Status"
            name="status"
            defaultValue={initialFilters.status}
            options={TASK_STATUS_OPTIONS}
          />
          <FilterSelect
            label="Task name"
            name="taskName"
            defaultValue={initialFilters.taskName}
            options={TASK_NAME_OPTIONS}
          />
          <FilterSelect
            label="Limit"
            name="limit"
            defaultValue={String(initialFilters.limit ?? 100)}
            options={[
              { value: "50", label: "50 rows" },
              { value: "100", label: "100 rows" },
              { value: "200", label: "200 rows" },
            ]}
          />
        </div>
        <FilterActions resetHref="/tasks" />
      </form>
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      <DataTable columns={columns} data={data?.items ?? []} />
      <div className="mt-2 text-xs text-slate-500">Total {data?.total ?? 0}</div>
    </>
  );
}

function formFilters(event: FormEvent<HTMLFormElement>): OpsVideoTaskFilters {
  const form = new FormData(event.currentTarget);
  return {
    channelId: positiveNumberFormValue(form.get("channelId")),
    status: stringFormValue(form.get("status")),
    taskName: stringFormValue(form.get("taskName")),
    limit: positiveNumberFormValue(form.get("limit")) ?? 100,
  };
}

function tasksHref(filters: OpsVideoTaskFilters): string {
  return hrefWithQuery("/tasks", filters);
}
