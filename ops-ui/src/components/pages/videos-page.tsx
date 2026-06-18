"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { useOpsVideos } from "@/lib/queries";
import { compactId, formatDateTime } from "@/lib/format";
import type { OpsVideo } from "@/lib/types";
import { useOpsStore } from "@/store/use-ops-store";

export function VideosPage() {
  const { videoSearch, videoTaskStatus, setVideoSearch, setVideoTaskStatus } = useOpsStore();
  const { data, isLoading, error } = useOpsVideos({
    search: videoSearch || undefined,
    taskStatus: videoTaskStatus || undefined,
    limit: 100,
    offset: 0,
  });

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
  ];

  return (
    <>
      <PageHeader
        title="Videos"
        actions={
          <>
            <input
              className="ops-input w-64"
              placeholder="Search title or YouTube ID"
              value={videoSearch}
              onChange={(event) => setVideoSearch(event.target.value)}
            />
            <select
              className="ops-input"
              value={videoTaskStatus}
              onChange={(event) => setVideoTaskStatus(event.target.value)}
            >
              <option value="">All task states</option>
              <option value="succeeded">Succeeded</option>
              <option value="running">Running</option>
              <option value="failed">Failed</option>
              <option value="timed_out">Timed out</option>
            </select>
          </>
        }
      />
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      <DataTable columns={columns} data={data?.items ?? []} />
      <div className="mt-2 text-xs text-slate-500">Total {data?.total ?? 0}</div>
    </>
  );
}
