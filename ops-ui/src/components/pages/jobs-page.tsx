"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { RotateCw } from "lucide-react";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { usePipelineJobs, useRetryJobMutation } from "@/lib/queries";
import { formatDateTime } from "@/lib/format";
import type { PipelineJobSummary } from "@/lib/types";

export function JobsPage() {
  const { data, isLoading, error } = usePipelineJobs();
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
      cell: ({ row }) =>
        row.original.status === "failed" ? (
          <button
            className="ops-button"
            disabled={retryJob.isPending}
            onClick={() => retryJob.mutate(row.original.jobId)}
          >
            <RotateCw size={15} />
            Retry
          </button>
        ) : (
          "-"
        ),
    },
  ];

  return (
    <>
      <PageHeader title="Pipeline Jobs" />
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      <DataTable columns={columns} data={data?.items ?? []} />
    </>
  );
}

function subjectLabel(job: PipelineJobSummary): string {
  if (!job.subjectType || job.subjectId === null || job.subjectId === undefined) {
    return job.externalKey ?? "-";
  }
  return `${job.subjectType} #${job.subjectId}`;
}
