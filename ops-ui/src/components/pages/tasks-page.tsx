"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Ban, RotateCw } from "lucide-react";
import type { FormEvent } from "react";
import { DataTable } from "@/components/data-table";
import { FilterActions, FilterInput, FilterSelect } from "@/components/filter-controls";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { ErrorState, LoadingState } from "@/components/ui-primitives";
import {
  useCancelWorkItemMutation,
  useRetryWorkItemMutation,
  useWorkItems,
} from "@/features/work/api";
import { compactId, formatDateTime } from "@/lib/format";
import type { WorkItem, WorkItemFilters, WorkItemStatus } from "@/lib/types";
import { hrefWithQuery, positiveNumberFormValue, stringFormValue } from "@/lib/url-filters";

type TasksPageProps = {
  initialFilters: WorkItemFilters;
};

const STATUS_OPTIONS = [
  { value: "", label: "All states" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "timed_out", label: "Timed out" },
  { value: "blocked", label: "Blocked" },
  { value: "canceled", label: "Canceled" },
];

const TASK_TYPE_OPTIONS = [
  { value: "", label: "All work types" },
  { value: "channel_resolve", label: "channel_resolve" },
  { value: "video_collect", label: "video_collect" },
  { value: "transcript_collect", label: "transcript_collect" },
  { value: "transcript_cue_generate", label: "transcript_cue_generate" },
  { value: "micro_event_extract", label: "micro_event_extract" },
  { value: "timeline_compose", label: "timeline_compose" },
  { value: "archive_publish", label: "archive_publish" },
];

export function TasksPage({ initialFilters }: TasksPageProps) {
  const router = useRouter();
  const { data, isLoading, error } = useWorkItems(initialFilters);
  const retry = useRetryWorkItemMutation();
  const cancel = useCancelWorkItemMutation();

  const columns: ColumnDef<WorkItem>[] = [
    {
      header: "Work",
      cell: ({ row }) => (
        <div>
          <div className="font-semibold">#{row.original.id} {row.original.taskType}</div>
          <div className="text-xs text-slate-500">{row.original.taskVersion}</div>
        </div>
      ),
    },
    {
      header: "Subject",
      cell: ({ row }) => (
        <div>
          <div>{subjectLabel(row.original)}</div>
          <div className="text-xs text-slate-500">{compactId(row.original.externalKey)}</div>
        </div>
      ),
    },
    {
      header: "State",
      cell: ({ row }) => (
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={row.original.status} />
          {row.original.outcomeCode ? (
            <span className="text-xs text-slate-600">{row.original.outcomeCode}</span>
          ) : null}
        </div>
      ),
    },
    {
      header: "Lease",
      cell: ({ row }) => (
        <div className="text-xs">
          <div>{row.original.leaseOwner ?? "-"}</div>
          <div className="text-slate-500">{formatDateTime(row.original.leaseExpiresAt)}</div>
        </div>
      ),
    },
    { header: "Updated", cell: ({ row }) => formatDateTime(row.original.updatedAt) },
    {
      header: "Error",
      cell: ({ row }) => (
        <div className="max-w-[360px] break-words text-xs text-slate-600">
          {row.original.errorType ?? row.original.errorCode ?? "-"}
          {row.original.errorMessage ? `: ${row.original.errorMessage}` : ""}
        </div>
      ),
    },
    {
      header: "Actions",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          {canRetry(row.original.status) ? (
            <button
              className="ops-button"
              disabled={retry.isPending}
              onClick={() => retry.mutate({ workItemId: row.original.id })}
              type="button"
            >
              <RotateCw aria-hidden="true" size={15} />
              Retry
            </button>
          ) : null}
          {canCancel(row.original.status) ? (
            <button
              className="ops-button"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate({ workItemId: row.original.id })}
              type="button"
            >
              <Ban aria-hidden="true" size={15} />
              Cancel
            </button>
          ) : null}
          {row.original.subjectType === "video" && row.original.subjectId ? (
            <Link className="ops-button" href={`/videos/${row.original.subjectId}`}>
              Video
            </Link>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Work Items"
        description="Inspect durable work, leases, outcomes, retries, and cancellations."
      />
      <form
        key={JSON.stringify(initialFilters)}
        className="ops-panel mb-4 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          router.push(tasksHref(formFilters(event)));
        }}
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <FilterSelect label="State" name="status" defaultValue={initialFilters.status} options={STATUS_OPTIONS} />
          <FilterSelect label="Work type" name="taskType" defaultValue={initialFilters.taskType} options={TASK_TYPE_OPTIONS} />
          <FilterInput label="Subject type" name="subjectType" defaultValue={initialFilters.subjectType} placeholder="video" />
          <FilterInput label="Subject ID" name="subjectId" defaultValue={initialFilters.subjectId} />
          <FilterSelect
            label="Limit"
            name="limit"
            defaultValue={String(initialFilters.limit ?? 50)}
            options={[50, 100, 200].map((value) => ({ value: String(value), label: `${value} rows` }))}
          />
        </div>
        <FilterActions resetHref="/tasks" />
      </form>
      {isLoading ? <LoadingState /> : null}
      {error ? <ErrorState message={String(error)} /> : null}
      <DataTable ariaLabel="Work items" columns={columns} data={data?.items ?? []} />
      <div className="mt-3 flex flex-wrap gap-2">
        {data?.nextCursor ? (
          <Link className="ops-button" href={tasksHref({ ...initialFilters, cursor: data.nextCursor })}>Older</Link>
        ) : null}
        {initialFilters.cursor ? (
          <Link className="ops-button" href={tasksHref({ ...initialFilters, cursor: undefined })}>Newest</Link>
        ) : null}
      </div>
    </>
  );
}

function subjectLabel(item: WorkItem) {
  return item.subjectId ? `${item.subjectType} #${item.subjectId}` : item.subjectType;
}

function canRetry(status: string) {
  return status === "failed" || status === "timed_out" || status === "blocked";
}

function canCancel(status: string) {
  return status === "pending" || status === "running" || status === "blocked";
}

function formFilters(event: FormEvent<HTMLFormElement>): WorkItemFilters {
  const form = new FormData(event.currentTarget);
  return {
    status: workStatus(form.get("status")),
    taskType: stringFormValue(form.get("taskType")),
    subjectType: stringFormValue(form.get("subjectType")),
    subjectId: positiveNumberFormValue(form.get("subjectId")),
    limit: positiveNumberFormValue(form.get("limit")) ?? 50,
  };
}

function workStatus(value: FormDataEntryValue | null): WorkItemStatus | undefined {
  const status = stringFormValue(value);
  return STATUS_OPTIONS.some((option) => option.value === status && status !== "")
    ? (status as WorkItemStatus)
    : undefined;
}

function tasksHref(filters: WorkItemFilters) {
  return hrefWithQuery("/tasks", filters);
}
