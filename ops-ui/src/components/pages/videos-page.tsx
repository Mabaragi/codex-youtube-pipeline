"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  CheckSquare,
  Eye,
  ListPlus,
  ListTree,
  Play,
  RefreshCw,
  ScrollText,
  Square,
  X,
} from "lucide-react";
import type { ChangeEvent, Dispatch, SetStateAction } from "react";
import { useMemo, useState } from "react";
import { DataTable } from "@/components/data-table";
import { EmbedStatusBadge } from "@/components/embed-status-badge";
import {
  ChannelFilterSelect,
  FilterActions,
  FilterInput,
  FilterSelect,
} from "@/components/filter-controls";
import { PageHeader } from "@/components/page-header";
import { PromptVersionSelect } from "@/components/prompt-version-select";
import { StatusBadge } from "@/components/status-badge";
import {
  ActionPanel,
  ErrorState,
  InlineNotice,
  LoadingState,
} from "@/components/ui-primitives";
import {
  useEnqueueMicroEventsMutation,
  useEnqueueTimelineComposeMutation,
  useExtractAllMicroEventsMutation,
  useOpsChannels,
  useOpsVideos,
  usePromptDetail,
  useRefreshVideoEmbedStatusMutation,
} from "@/lib/queries";
import {
  CODEX_MODEL_OPTIONS,
  CODEX_REASONING_EFFORT_OPTIONS,
  DEFAULT_CODEX_MODEL,
  DEFAULT_CODEX_REASONING_EFFORT,
} from "@/lib/codex-options";
import { compactId, formatDateTime } from "@/lib/format";
import type {
  MicroEventBatchExtractRequest,
  MicroEventEnqueueRequest,
  OpsVideo,
  OpsVideoFilters,
  OpsRefreshVideoEmbedStatusResponse,
  PromptDetail,
  TimelineComposeEnqueueRequest,
} from "@/lib/types";
import {
  hrefWithQuery,
  positiveNumberFormValue,
  stringFormValue,
} from "@/lib/url-filters";

type VideosPageProps = {
  initialFilters: OpsVideoFilters;
};

type MicroEventDefaults = {
  limit: number;
  model: NonNullable<MicroEventBatchExtractRequest["model"]>;
  reasoningEffort: NonNullable<MicroEventBatchExtractRequest["reasoningEffort"]>;
  retryFailed: boolean;
  regenerateSucceeded: boolean;
  windowMinutes: number;
  overlapMinutes: number;
  promptVersionId: number | null;
};

type TimelineComposeDefaults = {
  limit: number;
  model: NonNullable<TimelineComposeEnqueueRequest["model"]>;
  reasoningEffort: NonNullable<TimelineComposeEnqueueRequest["reasoningEffort"]>;
  retryFailed: boolean;
  regenerateSucceeded: boolean;
  copyStyle: NonNullable<TimelineComposeEnqueueRequest["copyStyle"]>;
  promptVersionId: number | null;
};

const VIDEO_TASK_STATUS_OPTIONS = [
  { value: "", label: "All task states" },
  { value: "succeeded", label: "Succeeded" },
  { value: "running", label: "Running" },
  { value: "failed", label: "Failed" },
  { value: "timed_out", label: "Timed out" },
  { value: "no_transcript", label: "No transcript" },
  { value: "skipped", label: "Skipped" },
  { value: "canceled", label: "Canceled" },
];

const EMBED_STATUS_OPTIONS = [
  { value: "", label: "All embed states" },
  { value: "embeddable", label: "Embeddable" },
  { value: "no_embed", label: "No embed" },
  { value: "unknown", label: "Unknown" },
];

export function VideosPage({ initialFilters }: VideosPageProps) {
  const router = useRouter();
  const { data: channelsData } = useOpsChannels();
  const { data, isLoading, error } = useOpsVideos(initialFilters);
  const extractAllMicroEvents = useExtractAllMicroEventsMutation();
  const enqueueMicroEvents = useEnqueueMicroEventsMutation();
  const enqueueTimelineCompose = useEnqueueTimelineComposeMutation();
  const refreshEmbedStatus = useRefreshVideoEmbedStatusMutation();
  const microEventPrompt = usePromptDetail("micro_event_extract");
  const timelinePrompt = usePromptDetail("timeline_compose");
  const videos = useMemo(() => data?.items ?? [], [data?.items]);
  const [selectedVideoIds, setSelectedVideoIds] = useState<Set<number>>(
    () => new Set(),
  );
  const [microEventDefaults, setMicroEventDefaults] = useState<MicroEventDefaults>({
    limit: 20,
    model: DEFAULT_CODEX_MODEL,
    reasoningEffort: DEFAULT_CODEX_REASONING_EFFORT,
    retryFailed: false,
    regenerateSucceeded: false,
    windowMinutes: 30,
    overlapMinutes: 5,
    promptVersionId: null,
  });
  const [timelineDefaults, setTimelineDefaults] = useState<TimelineComposeDefaults>({
    limit: 20,
    model: DEFAULT_CODEX_MODEL,
    reasoningEffort: DEFAULT_CODEX_REASONING_EFFORT,
    retryFailed: false,
    regenerateSucceeded: false,
    copyStyle: "LIGHT_FANDOM_V1",
    promptVersionId: null,
  });
  const visibleVideoIds = videos
    .filter((video) => video.isEmbeddable !== false)
    .map((video) => video.videoId);
  const selectedVisibleCount = visibleVideoIds.filter((videoId) =>
    selectedVideoIds.has(videoId),
  ).length;
  const allVisibleSelected =
    visibleVideoIds.length > 0 && selectedVisibleCount === visibleVideoIds.length;
  const applyFormFilters = (form: HTMLFormElement | null) => {
    if (form) {
      router.push(videosHref(formFilters(form)));
    }
  };
  const applySelectFilters = (event: ChangeEvent<HTMLSelectElement>) => {
    applyFormFilters(event.currentTarget.form);
  };
  const toggleVideoSelection = (videoId: number) => {
    const video = videos.find((item) => item.videoId === videoId);
    if (video?.isEmbeddable === false) {
      return;
    }
    setSelectedVideoIds((current) => {
      const next = new Set(current);
      if (next.has(videoId)) {
        next.delete(videoId);
      } else {
        next.add(videoId);
      }
      return next;
    });
  };
  const toggleVisibleSelection = () => {
    setSelectedVideoIds((current) => {
      const next = new Set(current);
      if (allVisibleSelected) {
        for (const videoId of visibleVideoIds) {
          next.delete(videoId);
        }
      } else {
        for (const videoId of visibleVideoIds) {
          next.add(videoId);
        }
      }
      return next;
    });
  };
  const clearSelection = () => {
    setSelectedVideoIds(new Set());
  };
  const queueSelected = () => {
    const videoIds = [...selectedVideoIds];
    if (!videoIds.length) {
      return;
    }
    enqueueMicroEvents.mutate(enqueueSelectedRequest(videoIds, microEventDefaults));
  };
  const queueOne = (videoId: number) => {
    enqueueMicroEvents.mutate(enqueueSelectedRequest([videoId], microEventDefaults));
  };
  const queueCurrentFilters = () => {
    enqueueMicroEvents.mutate(
      enqueueCurrentFiltersRequest(initialFilters, microEventDefaults),
    );
  };
  const queueSelectedTimelines = () => {
    const videoIds = [...selectedVideoIds];
    if (!videoIds.length) {
      return;
    }
    enqueueTimelineCompose.mutate(
      timelineSelectedRequest(videoIds, timelineDefaults),
    );
  };
  const queueOneTimeline = (videoId: number) => {
    enqueueTimelineCompose.mutate(timelineSelectedRequest([videoId], timelineDefaults));
  };
  const queueTimelineCurrentFilters = () => {
    enqueueTimelineCompose.mutate(
      timelineCurrentFiltersRequest(initialFilters, timelineDefaults),
    );
  };
  const runNow = () => {
    extractAllMicroEvents.mutate({
      limit: Math.min(Math.max(microEventDefaults.limit, 1), 5),
      model: microEventDefaults.model,
      reasoningEffort: microEventDefaults.reasoningEffort,
      retryFailed: microEventDefaults.retryFailed,
      regenerateSucceeded: microEventDefaults.regenerateSucceeded,
      windowMinutes: microEventDefaults.windowMinutes,
      overlapMinutes: microEventDefaults.overlapMinutes,
      includeNonEmbeddable: false,
      ...(microEventDefaults.promptVersionId
        ? { promptVersionId: microEventDefaults.promptVersionId }
        : {}),
    });
  };
  const refreshEmbedStatusNow = () => {
    const videoIds = [...selectedVideoIds];
    refreshEmbedStatus.mutate(
      videoIds.length > 0 ? { videoIds, limit: videoIds.length } : { limit: 200 },
    );
  };

  const columns: ColumnDef<OpsVideo>[] = [
    {
      id: "select",
      header: () => (
        <button
          aria-label={allVisibleSelected ? "Clear visible selection" : "Select visible videos"}
          className="inline-flex"
          onClick={toggleVisibleSelection}
          type="button"
        >
          {allVisibleSelected ? (
            <CheckSquare aria-hidden="true" size={16} />
          ) : (
            <Square aria-hidden="true" size={16} />
          )}
        </button>
      ),
      cell: ({ row }) => {
        const selected = selectedVideoIds.has(row.original.videoId);
        const noEmbed = row.original.isEmbeddable === false;
        return (
          <button
            aria-label={
              selected
                ? `Clear video ${row.original.videoId} selection`
                : `Select video ${row.original.videoId}`
            }
            className="inline-flex"
            disabled={noEmbed}
            onClick={() => toggleVideoSelection(row.original.videoId)}
            title={
              noEmbed
                ? "External playback is disabled for this video."
                : "Toggle video selection"
            }
            type="button"
          >
            {selected ? (
              <CheckSquare aria-hidden="true" size={16} />
            ) : (
              <Square aria-hidden="true" size={16} />
            )}
          </button>
        );
      },
    },
    {
      header: "Video",
      cell: ({ row }) => (
        <div>
          <div className="max-w-[520px] font-semibold">{row.original.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>{compactId(row.original.youtubeVideoId)}</span>
            <EmbedStatusBadge isEmbeddable={row.original.isEmbeddable} />
          </div>
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
      header: "Pipeline",
      cell: ({ row }) => <PipelineStatus generation={row.original.generation} />,
    },
    {
      header: "Action",
      cell: ({ row }) => {
        const noEmbed = row.original.isEmbeddable === false;
        const blockedTitle = "External playback is disabled for this video.";
        return (
          <div className="flex flex-wrap gap-2">
            <button
              className="ops-button"
              disabled={enqueueMicroEvents.isPending || noEmbed}
              onClick={() => queueOne(row.original.videoId)}
              title={
                noEmbed
                  ? blockedTitle
                  : enqueueMicroEvents.isPending
                    ? "Queue request is running"
                    : "Queue this video"
              }
              type="button"
            >
              <ListPlus aria-hidden="true" size={15} />
              Queue
            </button>
            <Link className="ops-button" href={`/videos/${row.original.videoId}`}>
              <Eye aria-hidden="true" size={15} />
              Details
            </Link>
            <button
              className="ops-button"
              disabled={enqueueTimelineCompose.isPending || noEmbed}
              onClick={() => queueOneTimeline(row.original.videoId)}
              title={
                noEmbed
                  ? blockedTitle
                  : enqueueTimelineCompose.isPending
                    ? "Timeline queue request is running"
                    : "Queue timeline compose for this video"
              }
              type="button"
            >
              <ListTree aria-hidden="true" size={15} />
              Timeline
            </button>
          </div>
        );
      },
    },
  ];

  return (
    <>
      <PageHeader
        title="Videos"
        description="Select stored videos, queue downstream work, and filter by task state."
        actions={
          <button
            className="ops-button"
            disabled={refreshEmbedStatus.isPending}
            onClick={refreshEmbedStatusNow}
            title={
              selectedVideoIds.size > 0
                ? "Refresh embed status for selected videos"
                : "Refresh embed status for the next stored videos"
            }
            type="button"
          >
            <RefreshCw aria-hidden="true" size={15} />
            {refreshEmbedStatus.isPending ? "Refreshing" : "Refresh embed status"}
          </button>
        }
      />
      <MicroEventBatchPanel
        allVisibleSelected={allVisibleSelected}
        defaults={microEventDefaults}
        enqueueMicroEvents={enqueueMicroEvents}
        extractAllMicroEvents={extractAllMicroEvents}
        onClearSelection={clearSelection}
        onQueueCurrentFilters={queueCurrentFilters}
        onQueueSelected={queueSelected}
        onRunNow={runNow}
        onToggleVisibleSelection={toggleVisibleSelection}
        promptDetail={microEventPrompt.data}
        promptLoading={microEventPrompt.isLoading}
        selectedCount={selectedVideoIds.size}
        setDefaults={setMicroEventDefaults}
        visibleCount={visibleVideoIds.length}
      />
      <TimelineComposePanel
        allVisibleSelected={allVisibleSelected}
        defaults={timelineDefaults}
        enqueueTimelineCompose={enqueueTimelineCompose}
        onClearSelection={clearSelection}
        onQueueCurrentFilters={queueTimelineCurrentFilters}
        onQueueSelected={queueSelectedTimelines}
        onToggleVisibleSelection={toggleVisibleSelection}
        promptDetail={timelinePrompt.data}
        promptLoading={timelinePrompt.isLoading}
        selectedCount={selectedVideoIds.size}
        setDefaults={setTimelineDefaults}
        visibleCount={visibleVideoIds.length}
      />
      <form
        key={JSON.stringify(initialFilters)}
        className="ops-panel mb-4 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          applyFormFilters(event.currentTarget);
        }}
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <ChannelFilterSelect
            channels={channelsData?.items ?? []}
            onChange={applySelectFilters}
            value={initialFilters.channelId}
          />
          <FilterInput
            label="Search"
            name="search"
            defaultValue={initialFilters.search}
            placeholder="Title or YouTube ID…"
          />
          <FilterSelect
            label="Task status"
            name="taskStatus"
            defaultValue={initialFilters.taskStatus}
            onChange={applySelectFilters}
            options={VIDEO_TASK_STATUS_OPTIONS}
          />
          <FilterSelect
            label="Embed status"
            name="embedStatus"
            defaultValue={initialFilters.embedStatus}
            onChange={applySelectFilters}
            options={EMBED_STATUS_OPTIONS}
          />
          <FilterInput label="Limit" name="limit" defaultValue={initialFilters.limit ?? 100} />
        </div>
        <FilterActions resetHref="/videos" />
      </form>
      {refreshEmbedStatus.error ? (
        <InlineNotice className="mb-4" tone="danger">
          {formatUnknownError(refreshEmbedStatus.error)}
        </InlineNotice>
      ) : null}
      {refreshEmbedStatus.data ? (
        <EmbedRefreshResult result={refreshEmbedStatus.data} />
      ) : null}
      {isLoading ? <LoadingState /> : null}
      {error ? <ErrorState message={String(error)} /> : null}
      <DataTable ariaLabel="Videos" columns={columns} data={videos} />
      <div className="mt-2 text-xs text-slate-500">Total {data?.total ?? 0}</div>
    </>
  );
}

type ExtractAllMicroEventsMutation = ReturnType<typeof useExtractAllMicroEventsMutation>;
type EnqueueMicroEventsMutation = ReturnType<typeof useEnqueueMicroEventsMutation>;
type EnqueueTimelineComposeMutation = ReturnType<
  typeof useEnqueueTimelineComposeMutation
>;

function MicroEventBatchPanel({
  allVisibleSelected,
  defaults,
  enqueueMicroEvents,
  extractAllMicroEvents,
  onClearSelection,
  onQueueCurrentFilters,
  onQueueSelected,
  onRunNow,
  onToggleVisibleSelection,
  promptDetail,
  promptLoading,
  selectedCount,
  setDefaults,
  visibleCount,
}: {
  allVisibleSelected: boolean;
  defaults: MicroEventDefaults;
  enqueueMicroEvents: EnqueueMicroEventsMutation;
  extractAllMicroEvents: ExtractAllMicroEventsMutation;
  onClearSelection: () => void;
  onQueueCurrentFilters: () => void;
  onQueueSelected: () => void;
  onRunNow: () => void;
  onToggleVisibleSelection: () => void;
  promptDetail: PromptDetail | undefined;
  promptLoading: boolean;
  selectedCount: number;
  setDefaults: Dispatch<SetStateAction<MicroEventDefaults>>;
  visibleCount: number;
}) {
  const enqueueResult = enqueueMicroEvents.data;
  const runNowResult = extractAllMicroEvents.data;
  const busy = enqueueMicroEvents.isPending || extractAllMicroEvents.isPending;
  const queueSelectedTitle =
    selectedCount === 0 ? "Select at least one video first" : "Queue selected videos";
  const visibleToggleLabel = allVisibleSelected ? "Clear visible" : "Select visible";

  const setNumberDefault =
    (key: "limit" | "windowMinutes" | "overlapMinutes") =>
    (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      const value = Number(event.currentTarget.value);
      setDefaults((current) => ({
        ...current,
        [key]: Number.isFinite(value) ? value : current[key],
      }));
    };
  const setStringDefault =
    (key: "model" | "reasoningEffort") =>
    (event: ChangeEvent<HTMLSelectElement>) => {
      const value = event.currentTarget.value;
      setDefaults((current) => ({
        ...current,
        [key]: value,
      }));
    };
  const setBooleanDefault =
    (key: "retryFailed" | "regenerateSucceeded") =>
    (event: ChangeEvent<HTMLInputElement>) => {
      const checked = event.currentTarget.checked;
      setDefaults((current) => ({
        ...current,
        [key]: checked,
      }));
    };
  const setPromptVersion = (versionId: number | null) => {
    setDefaults((current) => ({
      ...current,
      promptVersionId: versionId,
    }));
  };

  return (
    <ActionPanel
      className="mb-4"
      title="Micro Events"
      description={`Queue cue-ready videos for the worker. ${selectedCount} selected, ${visibleCount} visible.`}
      actions={
        <Link
          className="ops-button"
          href="/tasks?taskName=micro_event_extract&limit=100"
        >
          <ScrollText aria-hidden="true" size={15} />
          Tasks
        </Link>
      }
    >
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-7">
        <label className="grid gap-1 text-xs font-medium text-slate-600">
          Batch size
          <select
            className="ops-input"
            onChange={setNumberDefault("limit")}
            value={defaults.limit}
          >
            <option value="1">1 video</option>
            <option value="3">3 videos</option>
            <option value="5">5 videos</option>
            <option value="20">20 queued</option>
            <option value="50">50 queued</option>
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">
          Model
          <select
            className="ops-input"
            onChange={setStringDefault("model")}
            value={defaults.model}
          >
            {CODEX_MODEL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">
          Reasoning
          <select
            className="ops-input"
            onChange={setStringDefault("reasoningEffort")}
            value={defaults.reasoningEffort}
          >
            {CODEX_REASONING_EFFORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">
          Window
          <input
            autoComplete="off"
            className="ops-input"
            inputMode="numeric"
            max={240}
            min={1}
            onChange={setNumberDefault("windowMinutes")}
            type="number"
            value={defaults.windowMinutes}
          />
        </label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">
          Overlap
          <input
            autoComplete="off"
            className="ops-input"
            inputMode="numeric"
            max={239}
            min={0}
            onChange={setNumberDefault("overlapMinutes")}
            type="number"
            value={defaults.overlapMinutes}
          />
        </label>
        <PromptVersionSelect
          detail={promptDetail}
          disabled={busy}
          loading={promptLoading}
          onChange={setPromptVersion}
          value={defaults.promptVersionId}
        />
        <div className="grid gap-2 text-xs font-medium text-slate-600">
          <label className="flex items-center gap-2">
            <input
              checked={defaults.retryFailed}
              className="h-4 w-4"
              onChange={setBooleanDefault("retryFailed")}
              type="checkbox"
            />
            Retry failed
          </label>
          <label className="flex items-center gap-2">
            <input
              checked={defaults.regenerateSucceeded}
              className="h-4 w-4"
              onChange={setBooleanDefault("regenerateSucceeded")}
              type="checkbox"
            />
            Regenerate succeeded
          </label>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          className="ops-button ops-button-primary"
          disabled={busy || selectedCount === 0}
          onClick={onQueueSelected}
          title={queueSelectedTitle}
          type="button"
        >
          <ListPlus aria-hidden="true" size={15} />
          Queue selected ({selectedCount})
        </button>
        <button
          className="ops-button"
          disabled={busy}
          onClick={onQueueCurrentFilters}
          type="button"
        >
          <ListPlus aria-hidden="true" size={15} />
          Queue current filters
        </button>
        <button
          className="ops-button"
          disabled={visibleCount === 0}
          onClick={onToggleVisibleSelection}
          type="button"
        >
          {allVisibleSelected ? (
            <CheckSquare aria-hidden="true" size={15} />
          ) : (
            <Square aria-hidden="true" size={15} />
          )}
          {visibleToggleLabel}
        </button>
        <button
          className="ops-button"
          disabled={selectedCount === 0}
          onClick={onClearSelection}
          type="button"
        >
          <X aria-hidden="true" size={15} />
          Clear
        </button>
        <button
          className="ops-button"
          disabled={busy}
          onClick={onRunNow}
          title="Run the next eligible videos immediately"
          type="button"
        >
          <Play aria-hidden="true" size={15} />
          {extractAllMicroEvents.isPending ? "Running…" : "Run now"}
        </button>
        {enqueueMicroEvents.error ? (
          <InlineNotice tone="danger">
            {formatUnknownError(enqueueMicroEvents.error)}
          </InlineNotice>
        ) : null}
        {extractAllMicroEvents.error ? (
          <InlineNotice tone="danger">
            {formatUnknownError(extractAllMicroEvents.error)}
          </InlineNotice>
        ) : null}
      </div>
      {enqueueResult ? <MicroEventEnqueueResult result={enqueueResult} /> : null}
      {runNowResult ? <MicroEventRunNowResult result={runNowResult} /> : null}
    </ActionPanel>
  );
}

function TimelineComposePanel({
  allVisibleSelected,
  defaults,
  enqueueTimelineCompose,
  onClearSelection,
  onQueueCurrentFilters,
  onQueueSelected,
  onToggleVisibleSelection,
  promptDetail,
  promptLoading,
  selectedCount,
  setDefaults,
  visibleCount,
}: {
  allVisibleSelected: boolean;
  defaults: TimelineComposeDefaults;
  enqueueTimelineCompose: EnqueueTimelineComposeMutation;
  onClearSelection: () => void;
  onQueueCurrentFilters: () => void;
  onQueueSelected: () => void;
  onToggleVisibleSelection: () => void;
  promptDetail: PromptDetail | undefined;
  promptLoading: boolean;
  selectedCount: number;
  setDefaults: Dispatch<SetStateAction<TimelineComposeDefaults>>;
  visibleCount: number;
}) {
  const result = enqueueTimelineCompose.data;
  const queueSelectedTitle =
    selectedCount === 0 ? "Select at least one video first" : "Queue selected videos";
  const visibleToggleLabel = allVisibleSelected ? "Clear visible" : "Select visible";

  const setNumberDefault =
    (key: "limit") =>
    (event: ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      const value = Number(event.currentTarget.value);
      setDefaults((current) => ({
        ...current,
        [key]: Number.isFinite(value) ? value : current[key],
      }));
    };
  const setStringDefault =
    (key: "model" | "reasoningEffort" | "copyStyle") =>
    (event: ChangeEvent<HTMLSelectElement>) => {
      const value = event.currentTarget.value;
      setDefaults((current) => ({
        ...current,
        [key]: value,
      }));
    };
  const setBooleanDefault =
    (key: "retryFailed" | "regenerateSucceeded") =>
    (event: ChangeEvent<HTMLInputElement>) => {
      const checked = event.currentTarget.checked;
      setDefaults((current) => ({
        ...current,
        [key]: checked,
      }));
    };
  const setPromptVersion = (versionId: number | null) => {
    setDefaults((current) => ({
      ...current,
      promptVersionId: versionId,
    }));
  };

  return (
    <ActionPanel
      className="mb-4"
      title="Timeline Compose"
      description={`Queue videos with completed micro-events. ${selectedCount} selected, ${visibleCount} visible.`}
      actions={
        <Link
          className="ops-button"
          href="/tasks?taskName=timeline_compose&limit=100"
        >
          <ScrollText aria-hidden="true" size={15} />
          Tasks
        </Link>
      }
    >
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
        <label className="grid gap-1 text-xs font-medium text-slate-600">
          Batch size
          <select
            className="ops-input"
            onChange={setNumberDefault("limit")}
            value={defaults.limit}
          >
            <option value="1">1 video</option>
            <option value="3">3 videos</option>
            <option value="5">5 videos</option>
            <option value="20">20 queued</option>
            <option value="50">50 queued</option>
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">
          Model
          <select
            className="ops-input"
            onChange={setStringDefault("model")}
            value={defaults.model}
          >
            {CODEX_MODEL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">
          Reasoning
          <select
            className="ops-input"
            onChange={setStringDefault("reasoningEffort")}
            value={defaults.reasoningEffort}
          >
            {CODEX_REASONING_EFFORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-medium text-slate-600">
          Copy style
          <select
            className="ops-input"
            onChange={setStringDefault("copyStyle")}
            value={defaults.copyStyle}
          >
            <option value="LIGHT_FANDOM_V1">LIGHT_FANDOM_V1</option>
          </select>
        </label>
        <PromptVersionSelect
          detail={promptDetail}
          disabled={enqueueTimelineCompose.isPending}
          loading={promptLoading}
          onChange={setPromptVersion}
          value={defaults.promptVersionId}
        />
        <div className="grid gap-2 text-xs font-medium text-slate-600">
          <label className="flex items-center gap-2">
            <input
              checked={defaults.retryFailed}
              className="h-4 w-4"
              onChange={setBooleanDefault("retryFailed")}
              type="checkbox"
            />
            Retry failed
          </label>
          <label className="flex items-center gap-2">
            <input
              checked={defaults.regenerateSucceeded}
              className="h-4 w-4"
              onChange={setBooleanDefault("regenerateSucceeded")}
              type="checkbox"
            />
            Regenerate succeeded
          </label>
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          className="ops-button"
          disabled={enqueueTimelineCompose.isPending || selectedCount === 0}
          onClick={onQueueSelected}
          title={queueSelectedTitle}
          type="button"
        >
          <ListPlus aria-hidden="true" size={15} />
          Queue selected ({selectedCount})
        </button>
        <button
          className="ops-button"
          disabled={enqueueTimelineCompose.isPending}
          onClick={onQueueCurrentFilters}
          type="button"
        >
          <ListPlus aria-hidden="true" size={15} />
          Queue current filters
        </button>
        <button
          className="ops-button"
          disabled={visibleCount === 0}
          onClick={onToggleVisibleSelection}
          type="button"
        >
          {allVisibleSelected ? (
            <CheckSquare aria-hidden="true" size={15} />
          ) : (
            <Square aria-hidden="true" size={15} />
          )}
          {visibleToggleLabel}
        </button>
        <button
          className="ops-button"
          disabled={selectedCount === 0}
          onClick={onClearSelection}
          type="button"
        >
          <X aria-hidden="true" size={15} />
          Clear
        </button>
        {enqueueTimelineCompose.error ? (
          <InlineNotice tone="danger">
            {formatUnknownError(enqueueTimelineCompose.error)}
          </InlineNotice>
        ) : null}
      </div>
      {result ? <TimelineComposeEnqueueResult result={result} /> : null}
    </ActionPanel>
  );
}

function TimelineComposeEnqueueResult({
  result,
}: {
  result: NonNullable<EnqueueTimelineComposeMutation["data"]>;
}) {
  return (
    <div aria-live="polite" className="mt-4 border-t border-slate-200 pt-4" role="status">
      <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-4 xl:grid-cols-8">
        <Metric label="Queued" value={result.enqueuedCount} />
        <Metric label="Pending" value={result.alreadyPendingCount} />
        <Metric label="Running" value={result.alreadyRunningCount} />
        <Metric label="Succeeded" value={result.alreadySucceededCount} />
        <Metric label="Retry queued" value={result.retryQueuedCount} />
        <Metric label="Regenerated" value={result.regeneratedCount} />
        <Metric label="Failed skipped" value={result.failedSkippedCount} />
        <Metric label="Scanned" value={result.scannedCount} />
      </div>
      {result.items.length > 0 ? (
        <div className="mt-3 grid gap-2">
          {result.items.slice(0, 8).map((item) => (
            <div
              className="flex flex-wrap items-center gap-2 rounded border border-slate-200 px-3 py-2 text-xs"
              key={`${item.videoId}-${item.videoTaskId ?? item.reason}`}
            >
              <Link className="font-semibold" href={`/videos/${item.videoId}`}>
                #{item.videoId}
              </Link>
              <StatusBadge status={item.status} />
              <span>{item.reason}</span>
              {item.youtubeVideoId ? (
                <span className="text-slate-500">{compactId(item.youtubeVideoId)}</span>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function MicroEventEnqueueResult({
  result,
}: {
  result: NonNullable<EnqueueMicroEventsMutation["data"]>;
}) {
  return (
    <div aria-live="polite" className="mt-4 border-t border-slate-200 pt-4" role="status">
      <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-4 xl:grid-cols-8">
        <Metric label="Queued" value={result.enqueuedCount} />
        <Metric label="Pending" value={result.alreadyPendingCount} />
        <Metric label="Running" value={result.alreadyRunningCount} />
        <Metric label="Succeeded" value={result.alreadySucceededCount} />
        <Metric label="Skipped failed" value={result.skippedFailedCount} />
        <Metric label="Ineligible" value={result.ineligibleCount} />
        <Metric label="Scanned" value={result.scannedCount} />
        <Metric label="Requested" value={result.requestedCount} />
      </div>
      {result.items.length > 0 ? (
        <div className="mt-3 grid gap-2">
          {result.items.slice(0, 8).map((item) => (
            <div
              className="flex flex-wrap items-center gap-2 rounded border border-slate-200 px-3 py-2 text-xs"
              key={`${item.videoId}-${item.videoTaskId ?? item.reason}`}
            >
              <Link className="font-semibold" href={`/videos/${item.videoId}`}>
                #{item.videoId}
              </Link>
              <StatusBadge status={item.status} />
              <span>{item.reason}</span>
              {item.youtubeVideoId ? (
                <span className="text-slate-500">{compactId(item.youtubeVideoId)}</span>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function MicroEventRunNowResult({
  result,
}: {
  result: NonNullable<ExtractAllMicroEventsMutation["data"]>;
}) {
  return (
    <div aria-live="polite" className="mt-4 border-t border-slate-200 pt-4" role="status">
      <div className="grid gap-2 text-xs text-slate-600 md:grid-cols-4 xl:grid-cols-8">
        <Metric label="Processed" value={result.processedCount} />
        <Metric label="Succeeded" value={result.succeededCount} />
        <Metric label="Failed" value={result.failedCount} />
        <Metric label="Skipped" value={result.skippedCount} />
        <Metric label="Timed out" value={result.timedOutCount} />
        <Metric label="Scanned" value={result.scannedCount} />
        <Metric label="Satisfied" value={result.alreadySatisfiedCount} />
        <Metric label="Ineligible" value={result.ineligibleCount} />
      </div>
      {result.items.length > 0 ? (
        <div className="mt-3 grid gap-2">
          {result.items.map((item) => (
            <div
              className="flex flex-wrap items-center gap-2 rounded border border-slate-200 px-3 py-2 text-xs"
              key={`${item.videoId}-${item.videoTaskId ?? "none"}`}
            >
              <Link className="font-semibold" href={`/videos/${item.videoId}`}>
                #{item.videoId}
              </Link>
              <StatusBadge status={item.status} />
              <span>{item.reason}</span>
              <span className="text-slate-500">{compactId(item.youtubeVideoId)}</span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function EmbedRefreshResult({
  result,
}: {
  result: OpsRefreshVideoEmbedStatusResponse;
}) {
  return (
    <InlineNotice className="mb-4" tone={result.failedCount > 0 ? "warning" : "success"}>
      <div className="grid gap-2 text-xs md:grid-cols-4">
        <span>Scanned {result.scannedCount}</span>
        <span>Updated {result.updatedCount}</span>
        <span>Failed {result.failedCount}</span>
        <span>
          No embed{" "}
          {result.items.filter((item) => item.isEmbeddable === false).length}
        </span>
      </div>
      {result.items.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {result.items.slice(0, 8).map((item) => (
            <span
              className="rounded border border-slate-200 px-2 py-1"
              key={item.videoId}
            >
              #{item.videoId} {item.status}
              {item.isEmbeddable === false ? " / not embeddable" : ""}
            </span>
          ))}
        </div>
      ) : null}
    </InlineNotice>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="font-semibold text-slate-900">{value}</div>
      <div>{label}</div>
    </div>
  );
}

function PipelineStatus({ generation }: { generation: OpsVideo["generation"] }) {
  return (
    <div className="grid min-w-[230px] gap-1.5">
      <PipelineStage
        label="Cues"
        meta={cueGenerationMeta(generation.cues)}
        status={generationStatus(
          generation.cues.generated,
          generation.cues.latestTaskStatus,
        )}
      />
      <PipelineStage
        label="Micro"
        meta={microEventGenerationMeta(generation.microEvents)}
        status={generationStatus(
          generation.microEvents.generated,
          generation.microEvents.latestTaskStatus,
        )}
      />
      <PipelineStage
        label="Timeline"
        meta={timelineGenerationMeta(generation.timeline)}
        status={generationStatus(
          generation.timeline.generated,
          generation.timeline.latestTaskStatus,
        )}
      />
    </div>
  );
}

function PipelineStage({
  label,
  meta,
  status,
}: {
  label: string;
  meta: string;
  status: string;
}) {
  return (
    <div
      aria-label={`${label} generation ${status}`}
      className="flex min-w-0 items-center gap-2 text-xs"
    >
      <span className="w-14 shrink-0 font-medium text-slate-700">{label}</span>
      <StatusBadge status={status} />
      <span className="min-w-0 truncate text-slate-500">{meta}</span>
    </div>
  );
}

function generationStatus(
  generated: boolean,
  latestTaskStatus: string | null | undefined,
) {
  return generated ? "ready" : latestTaskStatus ?? "none";
}

function cueGenerationMeta(generation: OpsVideo["generation"]["cues"]) {
  if (generation.generated) {
    return `${formatCount(generation.cueCount, "cue")}, transcript #${generation.transcriptId ?? "-"}`;
  }
  if (generation.transcriptId) {
    return `0 cues, transcript #${generation.transcriptId}`;
  }
  return "No transcript";
}

function microEventGenerationMeta(
  generation: OpsVideo["generation"]["microEvents"],
) {
  if (generation.generated) {
    return `${formatCount(generation.microEventCount, "event")}, ${formatCount(generation.windowCount, "window")}`;
  }
  if (generation.latestTaskId) {
    return `task #${generation.latestTaskId}`;
  }
  return "No extraction";
}

function timelineGenerationMeta(generation: OpsVideo["generation"]["timeline"]) {
  if (generation.generated) {
    return `${formatCount(generation.episodeCount, "episode")}, composition #${generation.compositionId}`;
  }
  if (generation.latestTaskId) {
    return `task #${generation.latestTaskId}`;
  }
  return "No composition";
}

function formatCount(value: number, label: string) {
  return `${value} ${label}${value === 1 ? "" : "s"}`;
}

function formFilters(formElement: HTMLFormElement): OpsVideoFilters {
  const form = new FormData(formElement);
  return {
    channelId: positiveNumberFormValue(form.get("channelId")),
    search: stringFormValue(form.get("search")),
    taskStatus: stringFormValue(form.get("taskStatus")),
    embedStatus: embedStatusFormValue(form.get("embedStatus")),
    limit: positiveNumberFormValue(form.get("limit")) ?? 100,
  };
}

function videosHref(filters: OpsVideoFilters): string {
  return hrefWithQuery("/videos", filters);
}

function enqueueSelectedRequest(
  videoIds: number[],
  defaults: MicroEventDefaults,
): MicroEventEnqueueRequest {
  return {
    ...microEventRequestDefaults(defaults),
    target: "selected_videos",
    videoIds,
    limit: Math.min(videoIds.length, 200),
  };
}

function enqueueCurrentFiltersRequest(
  filters: OpsVideoFilters,
  defaults: MicroEventDefaults,
): MicroEventEnqueueRequest {
  return {
    ...microEventRequestDefaults(defaults),
    target: "current_filters",
    channelId: filters.channelId,
    taskStatus: videoTaskStatusValue(filters.taskStatus),
    search: filters.search || undefined,
  };
}

function timelineSelectedRequest(
  videoIds: number[],
  defaults: TimelineComposeDefaults,
): TimelineComposeEnqueueRequest {
  return {
    ...timelineRequestDefaults(defaults),
    target: "selected_videos",
    videoIds,
    limit: Math.min(videoIds.length, 200),
  };
}

function timelineCurrentFiltersRequest(
  filters: OpsVideoFilters,
  defaults: TimelineComposeDefaults,
): TimelineComposeEnqueueRequest {
  return {
    ...timelineRequestDefaults(defaults),
    target: "current_filters",
    channelId: filters.channelId,
    taskStatus: videoTaskStatusValue(filters.taskStatus),
    search: filters.search || undefined,
  };
}

function microEventRequestDefaults(
  defaults: MicroEventDefaults,
): Pick<
  MicroEventEnqueueRequest,
  | "includeNonEmbeddable"
  | "limit"
  | "model"
  | "overlapMinutes"
  | "reasoningEffort"
  | "regenerateSucceeded"
  | "retryFailed"
  | "windowMinutes"
  | "promptVersionId"
> {
  return {
    limit: Math.min(Math.max(defaults.limit, 1), 200),
    includeNonEmbeddable: false,
    model: defaults.model,
    reasoningEffort: defaults.reasoningEffort,
    retryFailed: defaults.retryFailed,
    regenerateSucceeded: defaults.regenerateSucceeded,
    windowMinutes: defaults.windowMinutes,
    overlapMinutes: defaults.overlapMinutes,
    ...(defaults.promptVersionId ? { promptVersionId: defaults.promptVersionId } : {}),
  };
}

function timelineRequestDefaults(
  defaults: TimelineComposeDefaults,
): Pick<
  TimelineComposeEnqueueRequest,
  | "copyStyle"
  | "includeNonEmbeddable"
  | "limit"
  | "model"
  | "reasoningEffort"
  | "regenerateSucceeded"
  | "retryFailed"
  | "promptVersionId"
> {
  return {
    limit: Math.min(Math.max(defaults.limit, 1), 200),
    includeNonEmbeddable: false,
    model: defaults.model,
    reasoningEffort: defaults.reasoningEffort,
    retryFailed: defaults.retryFailed,
    regenerateSucceeded: defaults.regenerateSucceeded,
    copyStyle: defaults.copyStyle,
    ...(defaults.promptVersionId ? { promptVersionId: defaults.promptVersionId } : {}),
  };
}

function videoTaskStatusValue(
  status: OpsVideoFilters["taskStatus"],
): MicroEventEnqueueRequest["taskStatus"] {
  if (
    status === "pending" ||
    status === "running" ||
    status === "succeeded" ||
    status === "failed" ||
    status === "timed_out" ||
    status === "no_transcript" ||
    status === "skipped" ||
    status === "canceled"
  ) {
    return status;
  }
  return undefined;
}

function embedStatusFormValue(
  value: FormDataEntryValue | null,
): OpsVideoFilters["embedStatus"] {
  const raw = stringFormValue(value);
  if (raw === "embeddable" || raw === "no_embed" || raw === "unknown") {
    return raw;
  }
  return undefined;
}

function formatUnknownError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
