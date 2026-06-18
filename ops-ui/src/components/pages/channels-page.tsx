"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { Captions, Download } from "lucide-react";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import {
  useCollectTranscriptsMutation,
  useCollectVideosMutation,
  useOpsChannels,
} from "@/lib/queries";
import { compactId, formatDateTime } from "@/lib/format";
import type { OpsChannel } from "@/lib/types";

export function ChannelsPage() {
  const { data, isLoading, error } = useOpsChannels();
  const collectVideos = useCollectVideosMutation();
  const collectTranscripts = useCollectTranscriptsMutation();

  const columns: ColumnDef<OpsChannel>[] = [
    {
      header: "Channel",
      cell: ({ row }) => (
        <div>
          <div className="font-semibold">{row.original.name}</div>
          <div className="text-xs text-slate-500">{row.original.handle}</div>
        </div>
      ),
    },
    { header: "Streamer", accessorKey: "streamerName" },
    {
      header: "YouTube",
      cell: ({ row }) => (
        <div className="text-xs">
          <div>{compactId(row.original.youtubeChannelId)}</div>
          <div className="text-slate-500">{compactId(row.original.uploadsPlaylistId)}</div>
        </div>
      ),
    },
    {
      header: "Videos",
      cell: ({ row }) => row.original.videoCount,
    },
    {
      header: "Tasks",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          <span>ok {row.original.transcriptSucceededCount}</span>
          <span>failed {row.original.taskFailedCount}</span>
          <span>running {row.original.taskRunningCount}</span>
        </div>
      ),
    },
    {
      header: "Latest",
      cell: ({ row }) => formatDateTime(row.original.latestVideoPublishedAt),
    },
    {
      header: "Actions",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          <button
            className="ops-button"
            disabled={collectVideos.isPending}
            onClick={() => collectVideos.mutate(row.original.channelId)}
            title="Collect latest videos"
          >
            <Download size={15} />
            Videos
          </button>
          <button
            className="ops-button ops-button-primary"
            disabled={collectTranscripts.isPending || row.original.taskRunningCount > 0}
            onClick={() =>
              collectTranscripts.mutate({ channelId: row.original.channelId, limit: 5 })
            }
            title="Collect transcripts for newest stored videos"
          >
            <Captions size={15} />
            Transcripts
          </button>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Channels" />
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      <div className="mb-3 flex gap-2 text-sm">
        <StatusBadge status={collectVideos.isPending ? "running" : "ready"} />
        <StatusBadge status={collectTranscripts.isPending ? "running" : "ready"} />
      </div>
      <DataTable columns={columns} data={data?.items ?? []} />
    </>
  );
}
