"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { RotateCw } from "lucide-react";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { useOpsVideoTasks, useRetryJobMutation } from "@/lib/queries";
import { compactId, formatDateTime } from "@/lib/format";
import type { OpsVideoTask } from "@/lib/types";

export function TasksPage() {
  const { data, isLoading, error } = useOpsVideoTasks({ limit: 100, offset: 0 });
  const retryJob = useRetryJobMutation();

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
      cell: ({ row }) =>
        row.original.jobId &&
        ["failed", "timed_out"].includes(row.original.status) ? (
          <button
            className="ops-button"
            disabled={retryJob.isPending}
            onClick={() => retryJob.mutate(row.original.jobId as number)}
          >
            <RotateCw size={15} />
            Retry job
          </button>
        ) : (
          "-"
        ),
    },
  ];

  return (
    <>
      <PageHeader title="Video Tasks" />
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      <DataTable columns={columns} data={data?.items ?? []} />
      <div className="mt-2 text-xs text-slate-500">Total {data?.total ?? 0}</div>
    </>
  );
}
