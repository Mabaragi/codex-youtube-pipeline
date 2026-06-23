"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { ArrowLeft, Captions, Download, ExternalLink, ListTree, Play } from "lucide-react";
import { useState } from "react";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import {
  fetchTranscriptContent,
  useExtractMicroEventsMutation,
  useMicroEventExtraction,
  useOpsVideoDetail,
  useTranscriptContent,
  useTranscriptCues,
} from "@/lib/queries";
import { compactId, formatDateTime } from "@/lib/format";
import type {
  AsrCorrectionCandidate,
  MicroEventCandidate,
  MicroEventExtractionDetail,
  MicroEventExtractionWindow,
  OpsVideoDetail,
  OpsVideoTask,
  TranscriptContent,
  TranscriptCue,
} from "@/lib/types";

type TranscriptMetadata = OpsVideoDetail["transcripts"][number];
type TranscriptSegment = TranscriptContent["segments"][number];
type TranscriptDownloadFormat = "srt" | "txt" | "json";

const TRANSCRIPT_DOWNLOAD_FORMATS: readonly TranscriptDownloadFormat[] = [
  "srt",
  "txt",
  "json",
];

export function VideoDetailPage({ videoId }: { videoId: number }) {
  const { data, isLoading, error } = useOpsVideoDetail(videoId);
  const latestCueTask = data?.tasks.find(
    (task) => task.taskName === "transcript_cue_generate",
  );
  const latestMicroEventTask = data?.tasks.find(
    (task) => task.taskName === "micro_event_extract",
  );
  const {
    data: microEventExtraction,
    isLoading: microEventLoading,
    error: microEventError,
  } = useMicroEventExtraction(videoId, Boolean(data));
  const extractMicroEvents = useExtractMicroEventsMutation();

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
                  <DetailRow
                    label="Cue task"
                    value={latestCueTask ? `#${latestCueTask.videoTaskId}` : "-"}
                    status={latestCueTask?.status}
                  />
                  <DetailRow label="Cue count" value={cueCountValue(latestCueTask)} />
                  <DetailRow
                    label="Micro events"
                    value={
                      latestMicroEventTask
                        ? `#${latestMicroEventTask.videoTaskId}`
                        : "-"
                    }
                    status={latestMicroEventTask?.status}
                  />
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

          <MicroEventExtractionPanel
            extraction={microEventExtraction}
            extractionError={microEventError}
            extractionLoading={microEventLoading}
            extractMicroEvents={extractMicroEvents}
            latestCueTask={latestCueTask}
            latestMicroEventTask={latestMicroEventTask}
            videoId={videoId}
          />

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

type ExtractMicroEventsMutation = ReturnType<typeof useExtractMicroEventsMutation>;

function MicroEventExtractionPanel({
  videoId,
  latestCueTask,
  latestMicroEventTask,
  extraction,
  extractionLoading,
  extractionError,
  extractMicroEvents,
}: {
  videoId: number;
  latestCueTask: OpsVideoTask | undefined;
  latestMicroEventTask: OpsVideoTask | undefined;
  extraction: MicroEventExtractionDetail | null | undefined;
  extractionLoading: boolean;
  extractionError: Error | null;
  extractMicroEvents: ExtractMicroEventsMutation;
}) {
  const hasSucceededCueTask = latestCueTask?.status === "succeeded";
  const taskIsRunning = latestMicroEventTask?.status === "running";
  const taskFailed =
    latestMicroEventTask?.status === "failed" ||
    latestMicroEventTask?.status === "timed_out";
  const taskSucceeded = latestMicroEventTask?.status === "succeeded";
  const disabled =
    !hasSucceededCueTask || taskIsRunning || extractMicroEvents.isPending;
  const actionLabel = taskFailed
    ? "Retry events"
    : taskSucceeded
      ? "Regenerate"
      : "Extract events";
  const actionTitle = !hasSucceededCueTask
    ? "Succeeded cue task required."
    : taskIsRunning
      ? "Micro-event extraction is already running."
      : actionLabel;

  function handleExtract() {
    extractMicroEvents.mutate({
      videoId,
      retryFailed: taskFailed,
      regenerateSucceeded: taskSucceeded,
    });
  }

  function handleDownloadJson() {
    if (!extraction) {
      return;
    }
    const file = buildMicroEventDownload(extraction);
    downloadTextFile(file.fileName, file.content, file.contentType);
  }

  return (
    <section className="ops-panel p-4">
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <ListTree size={16} />
          <h2 className="text-sm font-semibold">Micro Events</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {extraction ? (
            <button
              className="ops-button"
              onClick={handleDownloadJson}
              title="Download micro-event extraction JSON"
              type="button"
            >
              <Download size={14} />
              Download JSON
            </button>
          ) : null}
          <button
            className={`ops-button ${extraction ? "" : "ops-button-primary"}`}
            disabled={disabled}
            onClick={handleExtract}
            title={actionTitle}
            type="button"
          >
            <Play size={14} />
            {extractMicroEvents.isPending ? "Running..." : actionLabel}
          </button>
        </div>
      </div>

      {!hasSucceededCueTask ? (
        <div className="mb-3 text-xs text-slate-500">
          Succeeded transcript cues are required before extraction.
        </div>
      ) : null}
      {extractMicroEvents.error ? (
        <div className="mb-3 text-sm text-red-700">
          {formatUnknownError(extractMicroEvents.error)}
        </div>
      ) : null}
      {extractMicroEvents.data ? (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <span>Last request</span>
          <StatusBadge status={extractMicroEvents.data.status} />
          <span>{extractMicroEvents.data.reason}</span>
        </div>
      ) : null}
      {extractionLoading ? (
        <div className="text-sm text-slate-600">Loading...</div>
      ) : null}
      {extractionError ? (
        <div className="text-sm text-red-700">{String(extractionError)}</div>
      ) : null}
      {!extractionLoading && !extractionError && extraction === null ? (
        <div className="text-sm text-slate-500">No extraction yet.</div>
      ) : null}
      {extraction ? <MicroEventExtractionView extraction={extraction} /> : null}
    </section>
  );
}

function MicroEventExtractionView({
  extraction,
}: {
  extraction: MicroEventExtractionDetail;
}) {
  return (
    <div className="grid gap-3">
      <div className="grid gap-2 text-sm md:grid-cols-2 xl:grid-cols-4">
        <SummaryCell label="Status" status={extraction.status} value={extraction.status} />
        <SummaryCell label="Task" value={`#${extraction.videoTaskId}`} />
        <SummaryCell label="Transcript" value={idValue(extraction.transcriptId)} />
        <SummaryCell label="Job" value={idValue(extraction.jobId)} />
        <SummaryCell label="Windows" value={String(extraction.windowCount)} />
        <SummaryCell label="Events" value={String(extraction.microEventCount)} />
        <SummaryCell
          label="ASR candidates"
          value={String(extraction.asrCorrectionCandidateCount)}
        />
        <SummaryCell
          label="Cue range"
          value={formatCueIdRange(extraction.firstCueId, extraction.lastCueId)}
        />
      </div>
      {extraction.errorType ? (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-xs text-red-800">
          {extraction.errorType}
          {extraction.errorMessage ? `: ${extraction.errorMessage}` : ""}
        </div>
      ) : null}
      {extraction.windows.length === 0 ? (
        <div className="text-sm text-slate-500">No extraction windows.</div>
      ) : (
        <MicroEventWindowList windows={extraction.windows} />
      )}
    </div>
  );
}

function SummaryCell({
  label,
  value,
  status,
}: {
  label: string;
  value: string;
  status?: string | null;
}) {
  return (
    <div className="min-w-0 rounded border border-slate-200 p-2">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div className="mt-1 flex min-w-0 items-center gap-2 break-words">
        {status ? <StatusBadge status={status} /> : null}
        <span>{value}</span>
      </div>
    </div>
  );
}

function MicroEventWindowList({
  windows,
}: {
  windows: MicroEventExtractionWindow[];
}) {
  return (
    <div className="max-h-[680px] overflow-auto rounded border border-slate-200 bg-white">
      <div className="divide-y divide-slate-200">
        {windows.map((window) => (
          <MicroEventWindowItem key={window.windowId} window={window} />
        ))}
      </div>
    </div>
  );
}

function MicroEventWindowItem({
  window,
}: {
  window: MicroEventExtractionWindow;
}) {
  return (
    <div className="grid gap-3 p-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm font-semibold">
            <span>Window #{window.windowIndex}</span>
            <StatusBadge status={window.status} />
            {window.carryOutUnfinished ? (
              <span className="ops-status ops-status-warn">unfinished</span>
            ) : null}
          </div>
          <div className="mt-1 flex flex-wrap gap-3 text-xs text-slate-500">
            <span>{formatCueIdRange(window.startCueId, window.endCueId)}</span>
            <span>{window.cueCount} cues</span>
            <span>{window.microEvents.length} events</span>
            <span>{window.asrCorrectionCandidates.length} ASR</span>
          </div>
        </div>
        <div className="text-xs text-slate-500">
          job {idValue(window.sourceJobId)} / attempt {idValue(window.sourceJobAttemptId)}
        </div>
      </div>

      {window.validationError ? (
        <div className="rounded border border-red-200 bg-red-50 p-2 text-xs text-red-800">
          {window.validationError}
        </div>
      ) : null}

      <div className="grid gap-2">
        <div className="text-xs font-semibold uppercase text-slate-500">Events</div>
        {window.microEvents.length === 0 ? (
          <div className="text-sm text-slate-500">No micro-events.</div>
        ) : (
          <div className="rounded border border-slate-200">
            <div className="divide-y divide-slate-100">
              {window.microEvents.map((candidate) => (
                <MicroEventCandidateRow
                  candidate={candidate}
                  key={candidate.microEventCandidateId}
                />
              ))}
            </div>
          </div>
        )}
      </div>

      {window.asrCorrectionCandidates.length > 0 ? (
        <div className="grid gap-2">
          <div className="text-xs font-semibold uppercase text-slate-500">
            ASR Candidates
          </div>
          <div className="rounded border border-slate-200">
            <div className="divide-y divide-slate-100">
              {window.asrCorrectionCandidates.map((candidate) => (
                <AsrCorrectionCandidateRow
                  candidate={candidate}
                  key={candidate.asrCorrectionCandidateId}
                />
              ))}
            </div>
          </div>
        </div>
      ) : null}

      {window.rawResponseText ? (
        <details className="rounded border border-slate-200 bg-slate-50 p-2 text-xs">
          <summary className="cursor-pointer font-semibold text-slate-600">
            Raw response
          </summary>
          <pre className="mt-2 max-h-[260px] overflow-auto whitespace-pre-wrap break-words text-slate-700">
            {window.rawResponseText}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

function MicroEventCandidateRow({
  candidate,
}: {
  candidate: MicroEventCandidate;
}) {
  return (
    <div className="grid gap-3 p-2 text-xs md:grid-cols-[156px_minmax(0,1fr)_128px]">
      <div className="min-w-0">
        <StatusBadge status={candidate.activity} />
        <div className="mt-1 truncate font-mono text-slate-500">
          {formatCueIdRange(candidate.startCueId, candidate.endCueId)}
        </div>
      </div>
      <div className="min-w-0">
        <div className="break-words text-sm text-slate-800">{candidate.event}</div>
        <div className="mt-1 break-words font-mono text-slate-500">
          evidence {candidate.evidenceCueIds.join(", ")}
        </div>
      </div>
      <div className="grid content-start gap-1 text-slate-500">
        <span>{formatConfidence(candidate.confidence)}</span>
        <span>
          {candidate.boundaryBefore ? "boundary before" : ""}
          {candidate.boundaryBefore && candidate.boundaryAfter ? " / " : ""}
          {candidate.boundaryAfter ? "boundary after" : ""}
          {!candidate.boundaryBefore && !candidate.boundaryAfter ? "no boundary" : ""}
        </span>
      </div>
    </div>
  );
}

function AsrCorrectionCandidateRow({
  candidate,
}: {
  candidate: AsrCorrectionCandidate;
}) {
  return (
    <div className="grid gap-3 p-2 text-xs md:grid-cols-[minmax(0,1fr)_168px_104px]">
      <div className="min-w-0">
        <div className="break-words text-sm text-slate-800">
          {candidate.original} -&gt; {candidate.suggested}
        </div>
        <div className="mt-1 break-words font-mono text-slate-500">
          evidence {candidate.evidenceCueIds.join(", ")}
        </div>
      </div>
      <div className="grid content-start gap-1 text-slate-500">
        <span>{candidate.correctionType}</span>
        <span>{candidate.applyScope}</span>
      </div>
      <div className="text-slate-500">{formatConfidence(candidate.confidence)}</div>
    </div>
  );
}

function TranscriptItem({ transcript }: { transcript: TranscriptMetadata }) {
  const [expanded, setExpanded] = useState(false);
  const [cuesExpanded, setCuesExpanded] = useState(false);
  const [downloadingFormat, setDownloadingFormat] =
    useState<TranscriptDownloadFormat | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const { data, isLoading, error } = useTranscriptContent(transcript.id, expanded);
  const {
    data: cues,
    isLoading: cuesLoading,
    error: cuesError,
  } = useTranscriptCues(transcript.id, cuesExpanded);
  const hasTimeline = data ? data.segments.length > 0 : transcript.segmentCount > 0;

  async function handleDownload(format: TranscriptDownloadFormat) {
    if (downloadingFormat !== null) {
      return;
    }

    setDownloadingFormat(format);
    setDownloadError(null);
    try {
      const content = data ?? (await fetchTranscriptContent(transcript.id));
      if (format === "srt" && content.segments.length === 0) {
        setDownloadError("No timeline segments.");
        return;
      }
      const file = buildTranscriptDownload(content, transcript.id, format);
      downloadTextFile(file.fileName, file.content, file.contentType);
    } catch (downloadFailure) {
      setDownloadError(formatDownloadError(downloadFailure));
    } finally {
      setDownloadingFormat(null);
    }
  }

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
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="ops-button"
            onClick={() => setExpanded((current) => !current)}
            type="button"
          >
            {expanded ? "Hide transcript" : "Show transcript"}
          </button>
          <button
            className="ops-button"
            onClick={() => setCuesExpanded((current) => !current)}
            type="button"
          >
            {cuesExpanded ? "Hide cues" : "Show cues"}
          </button>
          <div className="flex flex-wrap gap-1">
            {TRANSCRIPT_DOWNLOAD_FORMATS.map((format) => {
              const isUnavailable = format === "srt" && !hasTimeline;
              const isDownloading = downloadingFormat === format;
              return (
                <button
                  className="ops-button"
                  disabled={downloadingFormat !== null || isUnavailable}
                  key={format}
                  onClick={() => void handleDownload(format)}
                  title={
                    isUnavailable
                      ? "No timeline segments."
                      : `Download ${format.toUpperCase()}`
                  }
                  type="button"
                >
                  <Download size={14} />
                  {isDownloading ? "..." : format.toUpperCase()}
                </button>
              );
            })}
          </div>
        </div>
      </div>
      {downloadError ? (
        <div className="mt-3 text-xs text-red-700">{downloadError}</div>
      ) : null}
      {expanded ? (
        <div className="mt-3 border-t border-slate-200 pt-3">
          {isLoading ? (
            <div className="text-sm text-slate-600">Loading...</div>
          ) : null}
          {error ? <div className="text-sm text-red-700">{String(error)}</div> : null}
          {data ? <TranscriptTimeline segments={data.segments} fallbackText={data.text} /> : null}
        </div>
      ) : null}
      {cuesExpanded ? (
        <div className="mt-3 border-t border-slate-200 pt-3">
          {cuesLoading ? (
            <div className="text-sm text-slate-600">Loading...</div>
          ) : null}
          {cuesError ? <div className="text-sm text-red-700">{String(cuesError)}</div> : null}
          {cues ? <TranscriptCueTable cues={cues.items} cueCount={cues.cueCount} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function TranscriptTimeline({
  segments,
  fallbackText,
}: {
  segments: TranscriptSegment[];
  fallbackText: string;
}) {
  if (segments.length === 0) {
    return (
      <pre className="max-h-[440px] overflow-auto whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-3 text-xs leading-relaxed text-slate-800">
        {fallbackText}
      </pre>
    );
  }

  return (
    <div className="max-h-[520px] overflow-auto rounded border border-slate-200 bg-white">
      <div className="grid grid-cols-[104px_minmax(0,1fr)] border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold uppercase text-slate-500">
        <div>Time</div>
        <div>Text</div>
      </div>
      <div className="divide-y divide-slate-100">
        {segments.map((segment, index) => (
          <div
            className="grid grid-cols-[104px_minmax(0,1fr)] gap-3 px-3 py-2 text-xs leading-relaxed"
            key={`${segment.start}-${index}`}
          >
            <time className="font-mono text-slate-500">
              {formatSegmentRange(segment.start, segment.duration)}
            </time>
            <div className="whitespace-pre-wrap break-words text-slate-800">{segment.text}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function TranscriptCueTable({
  cues,
  cueCount,
}: {
  cues: TranscriptCue[];
  cueCount: number;
}) {
  if (cues.length === 0) {
    return <div className="text-sm text-slate-500">No cues.</div>;
  }

  return (
    <div className="max-h-[520px] overflow-auto rounded border border-slate-200 bg-white">
      <div className="grid grid-cols-[132px_120px_88px_minmax(0,1fr)] border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold uppercase text-slate-500">
        <div>Cue</div>
        <div>Time</div>
        <div>Source</div>
        <div>Text</div>
      </div>
      <div className="divide-y divide-slate-100">
        {cues.map((cue) => (
          <div
            className="grid grid-cols-[132px_120px_88px_minmax(0,1fr)] gap-3 px-3 py-2 text-xs leading-relaxed"
            key={cue.id}
          >
            <div className="min-w-0">
              <div className="truncate font-mono text-slate-700" title={cue.cueId}>
                {cue.cueId}
              </div>
              <div className="text-slate-400">#{cue.cueIndex}</div>
            </div>
            <time className="font-mono text-slate-500">
              {formatCueRange(cue.startMs, cue.endMs)}
            </time>
            <div className="font-mono text-slate-500">seg #{cue.sourceSegmentIndex}</div>
            <div className="whitespace-pre-wrap break-words text-slate-800">{cue.text}</div>
          </div>
        ))}
      </div>
      <div className="border-t border-slate-200 px-3 py-2 text-xs text-slate-500">
        {cueCount} cues
      </div>
    </div>
  );
}

function formatSegmentRange(startSeconds: number, durationSeconds: number): string {
  const endSeconds = Math.max(startSeconds, startSeconds + durationSeconds);
  return `${formatTranscriptTime(startSeconds)}-${formatTranscriptTime(endSeconds)}`;
}

function formatCueRange(startMs: number, endMs: number): string {
  return `${formatTranscriptTime(startMs / 1000)}-${formatTranscriptTime(endMs / 1000)}`;
}

function formatTranscriptTime(totalSeconds: number): string {
  const totalCentiseconds = Math.max(0, Math.round(totalSeconds * 100));
  const wholeSeconds = Math.floor(totalCentiseconds / 100);
  const hours = Math.floor(wholeSeconds / 3600);
  const minutes = Math.floor((wholeSeconds % 3600) / 60);
  const seconds = wholeSeconds % 60;
  const centiseconds = totalCentiseconds % 100;
  const suffix = centiseconds > 0 ? `.${String(centiseconds).padStart(2, "0")}` : "";

  if (hours > 0) {
    return `${hours}:${padTime(minutes)}:${padTime(seconds)}${suffix}`;
  }
  return `${padTime(minutes)}:${padTime(seconds)}${suffix}`;
}

function padTime(value: number): string {
  return String(value).padStart(2, "0");
}

function buildTranscriptDownload(
  content: TranscriptContent,
  transcriptId: number,
  format: TranscriptDownloadFormat,
): {
  content: string;
  contentType: string;
  fileName: string;
} {
  const baseName = sanitizeFileName(
    `${content.videoId}-${content.languageCode}-${transcriptId}`,
  );
  if (format === "srt") {
    return {
      content: formatSrt(content.segments),
      contentType: "application/x-subrip;charset=utf-8",
      fileName: `${baseName}.srt`,
    };
  }
  if (format === "txt") {
    return {
      content: content.text,
      contentType: "text/plain;charset=utf-8",
      fileName: `${baseName}.txt`,
    };
  }
  return {
    content: JSON.stringify(content, null, 2),
    contentType: "application/json;charset=utf-8",
    fileName: `${baseName}.json`,
  };
}

function buildMicroEventDownload(extraction: MicroEventExtractionDetail): {
  content: string;
  contentType: string;
  fileName: string;
} {
  const baseName = sanitizeFileName(
    `${extraction.youtubeVideoId}-micro-events-task-${extraction.videoTaskId}`,
  );
  return {
    content: JSON.stringify(extraction, null, 2),
    contentType: "application/json;charset=utf-8",
    fileName: `${baseName}.json`,
  };
}

function formatSrt(segments: TranscriptSegment[]): string {
  return segments
    .map((segment, index) =>
      [
        String(index + 1),
        `${formatSrtTimestamp(segment.start)} --> ${formatSrtTimestamp(
          Math.max(segment.start, segment.start + segment.duration),
        )}`,
        segment.text.replace(/\r?\n/g, "\r\n"),
      ].join("\r\n"),
    )
    .join("\r\n\r\n");
}

function formatSrtTimestamp(totalSeconds: number): string {
  const totalMilliseconds = Math.max(0, Math.round(totalSeconds * 1000));
  const wholeSeconds = Math.floor(totalMilliseconds / 1000);
  const hours = Math.floor(wholeSeconds / 3600);
  const minutes = Math.floor((wholeSeconds % 3600) / 60);
  const seconds = wholeSeconds % 60;
  const milliseconds = totalMilliseconds % 1000;
  return `${padTime(hours)}:${padTime(minutes)}:${padTime(seconds)},${String(
    milliseconds,
  ).padStart(3, "0")}`;
}

function sanitizeFileName(value: string): string {
  return value.replace(/[^A-Za-z0-9._-]+/g, "-");
}

function downloadTextFile(fileName: string, content: string, contentType: string) {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = fileName;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function formatDownloadError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Download failed.";
}

function cueCountValue(task: OpsVideoTask | undefined): string {
  const cueCount = task?.outputJson?.cueCount;
  return typeof cueCount === "number" ? String(cueCount) : "-";
}

function idValue(value: number | null | undefined): string {
  return value === null || value === undefined ? "-" : `#${value}`;
}

function formatCueIdRange(
  startCueId: string | null | undefined,
  endCueId: string | null | undefined,
): string {
  if (!startCueId && !endCueId) {
    return "-";
  }
  if (startCueId === endCueId || !endCueId) {
    return startCueId ?? "-";
  }
  if (!startCueId) {
    return endCueId;
  }
  return `${startCueId}-${endCueId}`;
}

function formatConfidence(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatUnknownError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed.";
}
