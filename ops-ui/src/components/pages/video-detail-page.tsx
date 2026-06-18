"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { ArrowLeft, Captions, ExternalLink } from "lucide-react";
import { useState } from "react";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { useOpsVideoDetail, useTranscriptContent } from "@/lib/queries";
import { compactId, formatDateTime } from "@/lib/format";
import type { OpsVideoDetail, OpsVideoTask } from "@/lib/types";

type TranscriptMetadata = OpsVideoDetail["transcripts"][number];

export function VideoDetailPage({ videoId }: { videoId: number }) {
  const { data, isLoading, error } = useOpsVideoDetail(videoId);

  const taskColumns: ColumnDef<OpsVideoTask>[] = [
    {
      header: "Task",
      cell: ({ row }) => (
        <div>
          <div className="font-semibold">{row.original.taskName}</div>
          <div className="text-xs text-slate-500">{row.original.taskVersion}</div>
        </div>
      ),
    },
    { header: "Status", cell: ({ row }) => <StatusBadge status={row.original.status} /> },
    {
      header: "Job",
      cell: ({ row }) => (
        <div className="grid gap-1 text-xs text-slate-600">
          <span>{row.original.jobId ? `job #${row.original.jobId}` : "job -"}</span>
          <span>
            {row.original.jobAttemptId
              ? `attempt #${row.original.jobAttemptId}`
              : "attempt -"}
          </span>
        </div>
      ),
    },
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
  ];

  return (
    <>
      <PageHeader
        title="Video Detail"
        actions={
          <Link className="ops-button" href="/videos">
            <ArrowLeft size={15} />
            Videos
          </Link>
        }
      />
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      {data ? (
        <div className="grid gap-4">
          <section className="ops-panel p-4">
            <div className="grid gap-4 lg:grid-cols-[220px_minmax(0,1fr)]">
              {data.thumbnailUrl ? (
                <div
                  aria-label="Video thumbnail"
                  className="aspect-video w-full border border-slate-200 bg-cover bg-center"
                  role="img"
                  style={{ backgroundImage: `url(${data.thumbnailUrl})` }}
                />
              ) : (
                <div className="flex aspect-video items-center justify-center border border-slate-200 bg-slate-50 text-sm text-slate-500">
                  No thumbnail
                </div>
              )}
              <div className="min-w-0">
                <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="m-0 break-words text-lg font-semibold">{data.title}</h2>
                    <div className="mt-1 text-xs text-slate-500">
                      {data.channelName} · {compactId(data.youtubeVideoId)}
                    </div>
                  </div>
                  <a
                    className="ops-button"
                    href={`https://www.youtube.com/watch?v=${data.youtubeVideoId}`}
                    rel="noreferrer"
                    target="_blank"
                  >
                    <ExternalLink size={15} />
                    YouTube
                  </a>
                </div>
                <div className="grid gap-2 text-sm md:grid-cols-2 xl:grid-cols-3">
                  <DetailRow label="Published" value={formatDateTime(data.publishedAt)} />
                  <DetailRow label="Duration" value={data.duration ?? "-"} />
                  <DetailRow
                    label="Latest task"
                    value={data.latestTaskName ?? "-"}
                    status={data.latestTaskStatus}
                  />
                  <DetailRow label="Transcript" value={data.transcriptId ? `#${data.transcriptId}` : "-"} />
                  <DetailRow label="Listing API" value={idValue(data.sourceListingApiCallId)} />
                  <DetailRow label="Details API" value={idValue(data.sourceDetailsApiCallId)} />
                  <DetailRow label="Source job" value={idValue(data.sourceJobId)} />
                  <DetailRow label="Created" value={formatDateTime(data.createdAt)} />
                  <DetailRow label="Updated" value={formatDateTime(data.updatedAt)} />
                </div>
              </div>
            </div>
          </section>

          <section className="ops-panel p-4">
            <h2 className="mb-3 text-sm font-semibold">Description</h2>
            <div className="whitespace-pre-wrap break-words text-sm text-slate-700">
              {data.description || "No description."}
            </div>
          </section>

          <section className="grid gap-2">
            <h2 className="text-sm font-semibold">Task History</h2>
            <DataTable columns={taskColumns} data={data.tasks} emptyLabel="No tasks." />
          </section>

          <section className="ops-panel p-4">
            <div className="mb-3 flex items-center gap-2">
              <Captions size={16} />
              <h2 className="text-sm font-semibold">Transcripts</h2>
            </div>
            {data.transcripts.length === 0 ? (
              <div className="text-sm text-slate-500">No stored transcripts.</div>
            ) : (
              <div className="grid gap-3">
                {data.transcripts.map((transcript) => (
                  <TranscriptItem key={transcript.id} transcript={transcript} />
                ))}
              </div>
            )}
          </section>
        </div>
      ) : null}
    </>
  );
}

function DetailRow({
  label,
  value,
  status,
}: {
  label: string;
  value: string;
  status?: string | null;
}) {
  return (
    <div className="min-w-0 border-t border-slate-200 py-2">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div className="mt-1 flex min-w-0 items-center gap-2 break-words">
        {status ? <StatusBadge status={status} /> : null}
        <span>{value}</span>
      </div>
    </div>
  );
}

function TranscriptItem({ transcript }: { transcript: TranscriptMetadata }) {
  const [expanded, setExpanded] = useState(false);
  const { data, isLoading, error } = useTranscriptContent(transcript.id, expanded);

  return (
    <div className="rounded border border-slate-200 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="grid gap-1 text-sm">
          <div className="font-semibold">
            {transcript.language} · {transcript.languageCode}
          </div>
          <div className="flex flex-wrap gap-3 text-xs text-slate-500">
            <span>{transcript.isGenerated ? "generated" : "manual"}</span>
            <span>{transcript.segmentCount} segments</span>
            <span>{transcript.textLength} chars</span>
            <span>{formatDateTime(transcript.createdAt)}</span>
          </div>
        </div>
        <button
          className="ops-button"
          onClick={() => setExpanded((current) => !current)}
          type="button"
        >
          {expanded ? "Hide transcript" : "Show transcript"}
        </button>
      </div>
      {expanded ? (
        <div className="mt-3 border-t border-slate-200 pt-3">
          {isLoading ? (
            <div className="text-sm text-slate-600">Loading...</div>
          ) : null}
          {error ? <div className="text-sm text-red-700">{String(error)}</div> : null}
          {data ? (
            <pre className="max-h-[440px] overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-800">
              {data.text}
            </pre>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function idValue(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `#${value}`;
}
