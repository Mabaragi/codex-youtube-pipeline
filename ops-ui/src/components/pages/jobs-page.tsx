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
import { useOpsChannels, usePipelineJobs, useRetryJobMutation } from "@/lib/queries";
import { formatDateTime } from "@/lib/format";
import { logsHref } from "@/lib/logs";
import type { PipelineJobFilters, PipelineJobSummary } from "@/lib/types";
import {
  hrefWithQuery,
  positiveNumberFormValue,
  stringFormValue,
} from "@/lib/url-filters";

type JobsPageProps = {
  initialFilters: PipelineJobFilters;
};

const JOB_STATUS_OPTIONS = [
  { value: "", label: "All job states" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "skipped", label: "Skipped" },
  { value: "canceled", label: "Canceled" },
];

const JOB_STEP_OPTIONS = [
  { value: "", label: "All steps" },
  { value: "channel_resolve", label: "channel_resolve" },
  { value: "video_collect", label: "video_collect" },
  { value: "transcript_collect_batch", label: "transcript_collect_batch" },
  { value: "transcript_collect", label: "transcript_collect" },
];

export function JobsPage({ initialFilters }: JobsPageProps) {
  const router = useRouter();
  const { data: channelsData } = useOpsChannels();
  const { data, isLoading, error } = usePipelineJobs(initialFilters);
  const retryJob = useRetryJobMutation();

  const columns: ColumnDef<PipelineJobSummary>[] = [
    { header: "Job", cell: ({ row }) => `#${row.original.jobId}` },
    { header: "Step", accessorKey: "step" },
    { header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    { header: "Subject", cell: ({ row }) => subjectLabel(row.original) },
    { header: "Attempts", accessorKey: "attemptCount" },
    { header: "Updated", cell: ({ row }) => formatDateTime(row.original.updatedAt) },
    {
      header: "Action",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          {row.original.status === "failed" ? (
            <button
              className="ops-button"
              disabled={retryJob.isPending}
              onClick={() => retryJob.mutate(row.original.jobId)}
            >
              <RotateCw size={15} />
              Retry
            </button>
          ) : null}
          <Link className="ops-button" href={logsHref({ jobId: row.original.jobId })}>
            <ScrollText size={15} />
            Logs
          </Link>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Pipeline Jobs" />
      <form
        key={JSON.stringify(initialFilters)}
        className="ops-panel mb-4 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          router.push(jobsHref(formFilters(event)));
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
            options={JOB_STATUS_OPTIONS}
          />
          <FilterSelect
            label="Step"
            name="step"
            defaultValue={initialFilters.step}
            options={JOB_STEP_OPTIONS}
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
        </div>
        <FilterActions resetHref="/jobs" />
      </form>
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      <DataTable columns={columns} data={data?.items ?? []} />
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {data?.nextCursor ? (
          <Link
            className="ops-button"
            href={jobsHref({ ...initialFilters, cursor: data.nextCursor })}
          >
            Older
          </Link>
        ) : null}
        {initialFilters.cursor ? (
          <Link
            className="ops-button"
            href={jobsHref({ ...initialFilters, cursor: undefined })}
          >
            Newest
          </Link>
        ) : null}
      </div>
    </>
  );
}

function subjectLabel(job: PipelineJobSummary): string {
  if (!job.subjectType || job.subjectId === null || job.subjectId === undefined) {
    return job.externalKey ?? "-";
  }
  return `${job.subjectType} #${job.subjectId}`;
}

function formFilters(event: FormEvent<HTMLFormElement>): PipelineJobFilters {
  const form = new FormData(event.currentTarget);
  return {
    channelId: positiveNumberFormValue(form.get("channelId")),
    status: pipelineStatusValue(form.get("status")),
    step: stringFormValue(form.get("step")),
    limit: positiveNumberFormValue(form.get("limit")) ?? 50,
  };
}

function pipelineStatusValue(
  value: FormDataEntryValue | null,
): PipelineJobFilters["status"] | undefined {
  const text = stringFormValue(value);
  if (
    text === "pending" ||
    text === "running" ||
    text === "succeeded" ||
    text === "failed" ||
    text === "skipped" ||
    text === "canceled"
  ) {
    return text;
  }
  return undefined;
}

function jobsHref(filters: PipelineJobFilters): string {
  return hrefWithQuery("/jobs", filters);
}
