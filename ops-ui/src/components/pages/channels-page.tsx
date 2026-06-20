"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { Captions, Download, Plus, Search } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import { TranscriptCollectionStatus } from "@/components/transcript-collection-status";
import {
  useCollectAllTranscriptsMutation,
  useCollectTranscriptsMutation,
  useCollectVideosMutation,
  useCreateStreamerMutation,
  useOpsChannels,
  useResolveStreamerChannelMutation,
  useRunningTranscriptBatches,
  useRunningTranscriptTasks,
  useStreamers,
} from "@/lib/queries";
import { compactId, formatDateTime } from "@/lib/format";
import {
  buildTranscriptCollectionLock,
  transcriptCollectionActionTitle,
} from "@/lib/transcript-collection-lock";
import type { OpsChannel, ResolveYouTubeChannelResult, Streamer } from "@/lib/types";

const STREAMER_OPTIONS_ID = "streamer-name-options";

export function ChannelsPage() {
  const { data, isLoading, error } = useOpsChannels();
  const streamers = useStreamers();
  const runningTranscriptTasks = useRunningTranscriptTasks();
  const runningTranscriptBatches = useRunningTranscriptBatches();
  const collectVideos = useCollectVideosMutation();
  const collectAllTranscripts = useCollectAllTranscriptsMutation();
  const collectTranscripts = useCollectTranscriptsMutation();
  const createStreamer = useCreateStreamerMutation();
  const resolveChannel = useResolveStreamerChannelMutation();
  const [newStreamerName, setNewStreamerName] = useState("");
  const [resolveStreamerName, setResolveStreamerName] = useState("");
  const [resolveHandle, setResolveHandle] = useState("");
  const [createFeedback, setCreateFeedback] = useState<Feedback | null>(null);
  const [resolveFeedback, setResolveFeedback] = useState<Feedback | null>(null);
  const streamerItems = useMemo(() => streamers.data ?? [], [streamers.data]);
  const trimmedNewStreamerName = newStreamerName.trim();
  const trimmedResolveStreamerName = resolveStreamerName.trim();
  const trimmedResolveHandle = resolveHandle.trim();
  const isStreamerListUnavailable = streamers.isLoading || Boolean(streamers.error);
  const isCreateDisabled = !trimmedNewStreamerName || createStreamer.isPending;
  const isResolveDisabled =
    !trimmedResolveStreamerName ||
    !trimmedResolveHandle ||
    isStreamerListUnavailable ||
    createStreamer.isPending ||
    resolveChannel.isPending;
  const totalStoredVideoCount = (data?.items ?? []).reduce(
    (total, item) => total + item.videoCount,
    0,
  );
  const isAnyTranscriptMutationPending =
    collectTranscripts.isPending || collectAllTranscripts.isPending;
  const transcriptLock = buildTranscriptCollectionLock({
    runningTasks: runningTranscriptTasks.data,
    runningBatches: runningTranscriptBatches.data,
    tasksLoading: runningTranscriptTasks.isLoading,
    batchesLoading: runningTranscriptBatches.isLoading,
    tasksError: runningTranscriptTasks.isError,
    batchesError: runningTranscriptBatches.isError,
    mutationPending: isAnyTranscriptMutationPending,
  });
  const isTranscriptCollectionDisabled = transcriptLock.isLocked;
  const isAllTranscriptCollectionDisabled =
    isTranscriptCollectionDisabled || totalStoredVideoCount < 1;
  const transcriptButtonTitle = transcriptTaskButtonTitle({
    lock: transcriptLock,
  });
  const allTranscriptButtonTitle = allTranscriptTaskButtonTitle({
    lock: transcriptLock,
    totalStoredVideoCount,
  });
  const transcriptButtonLabel = transcriptTaskButtonLabel({
    lock: transcriptLock,
  });

  async function handleCreateStreamer(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isCreateDisabled) {
      return;
    }
    setCreateFeedback(null);
    try {
      const created = await createStreamer.mutateAsync({
        name: trimmedNewStreamerName,
      });
      setNewStreamerName("");
      setResolveStreamerName(created.name);
      setCreateFeedback({
        tone: "success",
        message: `Added streamer ${created.name}.`,
      });
    } catch (createError) {
      setCreateFeedback({
        tone: "error",
        message: `Add failed: ${formatMutationError(createError)}`,
      });
    }
  }

  async function handleResolveChannel(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isResolveDisabled) {
      return;
    }
    setResolveFeedback(null);
    try {
      const { streamer, created } = await getOrCreateStreamer({
        streamers: streamerItems,
        name: trimmedResolveStreamerName,
        createStreamer: createStreamer.mutateAsync,
      });
      const resolved = await resolveChannel.mutateAsync({
        streamerId: streamer.id,
        handle: trimmedResolveHandle,
      });
      setResolveStreamerName(streamer.name);
      setResolveHandle("");
      setResolveFeedback({
        tone: "success",
        message: resolveSuccessMessage(resolved, created, streamer.name),
      });
    } catch (resolveError) {
      setResolveFeedback({
        tone: "error",
        message: `Resolve failed: ${formatMutationError(resolveError)}`,
      });
    }
  }

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
            disabled={isTranscriptCollectionDisabled || row.original.videoCount < 1}
            onClick={() =>
              collectTranscripts.mutate({
                channelId: row.original.channelId,
                limit: row.original.videoCount,
              })
            }
            title={
              row.original.videoCount < 1
                ? "No stored videos to collect transcripts for"
                : transcriptButtonTitle
            }
          >
            <Captions size={15} />
            {transcriptButtonLabel}
          </button>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        actions={
          <button
            className="ops-button ops-button-primary"
            disabled={isAllTranscriptCollectionDisabled}
            onClick={() => collectAllTranscripts.mutate({})}
            title={allTranscriptButtonTitle}
          >
            <Captions size={15} />
            All transcripts
          </button>
        }
        title="Channels"
      />
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      <div className="ops-panel mb-4 grid gap-4 p-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <form onSubmit={handleCreateStreamer}>
          <div className="mb-2 text-sm font-semibold">Add streamer</div>
          <div className="flex flex-wrap gap-2">
            <input
              aria-label="Streamer name"
              className="ops-input min-w-0 flex-1"
              maxLength={255}
              onChange={(event) => setNewStreamerName(event.target.value)}
              placeholder="Streamer name"
              value={newStreamerName}
            />
            <button
              className="ops-button"
              disabled={isCreateDisabled}
              title="Add streamer"
              type="submit"
            >
              <Plus size={15} />
              Add
            </button>
          </div>
          <InlineFeedback feedback={createFeedback} />
        </form>
        <form onSubmit={handleResolveChannel}>
          <div className="mb-2 text-sm font-semibold">Resolve channel</div>
          <div className="flex flex-wrap gap-2">
            <input
              aria-label="Streamer for resolve"
              className="ops-input min-w-[180px] flex-1"
              list={STREAMER_OPTIONS_ID}
              maxLength={255}
              onChange={(event) => setResolveStreamerName(event.target.value)}
              placeholder="Streamer"
              value={resolveStreamerName}
            />
            <datalist data-testid="streamer-options" id={STREAMER_OPTIONS_ID}>
              {streamerItems.map((streamer) => (
                <option key={streamer.id} value={streamer.name}>
                  {streamer.name}
                </option>
              ))}
            </datalist>
            <input
              aria-label="YouTube handle"
              className="ops-input min-w-[180px] flex-1"
              maxLength={255}
              onChange={(event) => setResolveHandle(event.target.value)}
              placeholder="@youtube-handle"
              value={resolveHandle}
            />
            <button
              className="ops-button ops-button-primary"
              disabled={isResolveDisabled}
              title={resolveButtonTitle({
                isStreamerListUnavailable,
                isPending: createStreamer.isPending || resolveChannel.isPending,
              })}
              type="submit"
            >
              <Search size={15} />
              Resolve
            </button>
          </div>
          {streamers.isLoading ? (
            <div className="mt-2 text-xs text-slate-600">Loading streamers...</div>
          ) : null}
          {streamers.error ? (
            <div className="mt-2 text-xs text-red-700">
              Cannot load streamers. Resolve is disabled.
            </div>
          ) : null}
          <InlineFeedback feedback={resolveFeedback} />
        </form>
      </div>
      <TranscriptCollectionStatus
        className="mb-3"
        showIdle
        state={transcriptLock}
      />
      <div className="mb-3 flex gap-2 text-sm">
        <span className="text-xs text-slate-500">Video collect</span>
        <StatusBadge status={collectVideos.isPending ? "running" : "ready"} />
      </div>
      <DataTable columns={columns} data={data?.items ?? []} />
    </>
  );
}

type Feedback = {
  tone: "success" | "error";
  message: string;
};

function InlineFeedback({ feedback }: { feedback: Feedback | null }) {
  if (feedback === null) {
    return null;
  }
  const tone = feedback.tone === "success" ? "text-emerald-700" : "text-red-700";
  return <div className={`mt-2 text-xs ${tone}`}>{feedback.message}</div>;
}

async function getOrCreateStreamer({
  streamers,
  name,
  createStreamer,
}: {
  streamers: Streamer[];
  name: string;
  createStreamer: (request: { name: string }) => Promise<Streamer>;
}): Promise<{ streamer: Streamer; created: boolean }> {
  const existing = findStreamerByName(streamers, name);
  if (existing !== null) {
    return { streamer: existing, created: false };
  }
  return {
    streamer: await createStreamer({ name }),
    created: true,
  };
}

function findStreamerByName(streamers: Streamer[], name: string): Streamer | null {
  const exact = streamers.find((streamer) => streamer.name === name);
  if (exact !== undefined) {
    return exact;
  }
  const normalized = name.toLocaleLowerCase();
  return (
    streamers.find(
      (streamer) => streamer.name.toLocaleLowerCase() === normalized,
    ) ?? null
  );
}

function resolveSuccessMessage(
  resolved: ResolveYouTubeChannelResult,
  created: boolean,
  streamerName: string,
) {
  const prefix = created ? `Added streamer ${streamerName} and resolved` : "Resolved";
  return `${prefix} ${resolved.name} (${compactId(resolved.youtubeChannelId)}).`;
}

function resolveButtonTitle({
  isStreamerListUnavailable,
  isPending,
}: {
  isStreamerListUnavailable: boolean;
  isPending: boolean;
}) {
  if (isPending) {
    return "Resolving channel";
  }
  if (isStreamerListUnavailable) {
    return "Streamer list is unavailable";
  }
  return "Resolve YouTube channel";
}

function formatMutationError(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function transcriptTaskButtonTitle({
  lock,
}: {
  lock: ReturnType<typeof buildTranscriptCollectionLock>;
}) {
  if (lock.isLocked) {
    return transcriptCollectionActionTitle(lock);
  }
  return "Collect transcripts for this channel's stored videos";
}

function allTranscriptTaskButtonTitle({
  lock,
  totalStoredVideoCount,
}: {
  lock: ReturnType<typeof buildTranscriptCollectionLock>;
  totalStoredVideoCount: number;
}) {
  if (totalStoredVideoCount < 1) {
    return "No stored videos to collect transcripts for";
  }
  if (lock.isLocked) {
    return transcriptCollectionActionTitle(lock);
  }
  return "Collect transcripts for all stored videos";
}

function transcriptTaskButtonLabel({
  lock,
}: {
  lock: ReturnType<typeof buildTranscriptCollectionLock>;
}) {
  if (lock.status === "checking") {
    return "Checking";
  }
  if (lock.status === "unavailable") {
    return "Blocked";
  }
  if (lock.isLocked) {
    return "Running";
  }
  return "Transcripts";
}
