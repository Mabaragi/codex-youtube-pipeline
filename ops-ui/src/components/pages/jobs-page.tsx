"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { RotateCw, ScrollText } from "lucide-react";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { usePipelineJobs, useRetryJobMutation } from "@/lib/queries";
import { formatDateTime } from "@/lib/format";
import { logsHref } from "@/lib/logs";
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
