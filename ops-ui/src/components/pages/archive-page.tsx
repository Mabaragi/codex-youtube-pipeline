"use client";

import type { ColumnDef } from "@tanstack/react-table";
import {
  CheckSquare,
  ExternalLink,
  ListPlus,
  ScrollText,
  Square,
  UploadCloud,
  X,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ChangeEvent } from "react";
import { useMemo, useState } from "react";
import { DataTable } from "@/components/data-table";
import {
  ChannelFilterSelect,
  FilterActions,
  FilterInput,
  FilterSelect,
} from "@/components/filter-controls";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/status-badge";
import {
  ActionPanel,
  ErrorState,
  InlineNotice,
  LoadingState,
  MetricStrip,
} from "@/components/ui-primitives";
import { compactId, formatDateTime } from "@/lib/format";
import { logsHref } from "@/lib/logs";
import {
  useArchiveCurrent,
  useArchiveVideos,
  useOpsChannels,
  usePublishArchiveMutation,
} from "@/lib/queries";
import type {
  ArchiveOpsVideo,
  ArchiveOpsVideoFilters,
  ArchivePublishRequest,
  ArchivePublishResult,
} from "@/lib/types";
import {
  hrefWithQuery,
  positiveNumberFormValue,
  stringFormValue,
} from "@/lib/url-filters";

type ArchivePageProps = {
  initialFilters: ArchiveOpsVideoFilters;
};

type PublishDefaults = {
  environment: string;
  variant: string;
  schemaVersion: number;
  limit: number;
  retryFailed: boolean;
  regenerateSucceeded: boolean;
};

const PUBLISH_STATUS_OPTIONS = [
  { value: "", label: "All publish states" },
  { value: "not_ready", label: "Not ready" },
  { value: "ready", label: "Ready" },
  { value: "pending", label: "Pending" },
  { value: "running", label: "Running" },
  { value: "failed", label: "Failed" },
  { value: "published", label: "Published" },
];

export function ArchivePage({ initialFilters }: ArchivePageProps) {
  const router = useRouter();
  const { data: channelsData } = useOpsChannels();
  const environment = initialFilters.environment ?? "prod";
  const { data: current, isLoading: currentLoading, error: currentError } =
    useArchiveCurrent(environment);
  const { data, isLoading, error } = useArchiveVideos(initialFilters);
  const publishArchive = usePublishArchiveMutation();
  const videos = useMemo(() => data?.items ?? [], [data?.items]);
  const [selectedVideoIds, setSelectedVideoIds] = useState<Set<number>>(
    () => new Set(),
  );
  const [lastResult, setLastResult] = useState<ArchivePublishResult | null>(null);
  const [defaults, setDefaults] = useState<PublishDefaults>({
    environment,
    variant: "control",
    schemaVersion: 1,
    limit: 20,
    retryFailed: false,
    regenerateSucceeded: false,
  });

  const visibleVideoIds = videos.map((video) => video.videoId);
  const selectedVisibleCount = visibleVideoIds.filter((videoId) =>
    selectedVideoIds.has(videoId),
  ).length;
  const allVisibleSelected =
    visibleVideoIds.length > 0 && selectedVisibleCount === visibleVideoIds.length;
  const pending = publishArchive.isPending;

  const applySelectFilters = (event: ChangeEvent<HTMLSelectElement>) => {
    const form = event.currentTarget.form;
    if (form) {
      router.push(archiveHref(formFilters(form)));
    }
  };

  const toggleVisibleSelection = () => {
    setSelectedVideoIds((currentSelection) => {
      const next = new Set(currentSelection);
      for (const videoId of visibleVideoIds) {
        if (allVisibleSelected) {
          next.delete(videoId);
        } else {
          next.add(videoId);
        }
      }
      return next;
    });
  };

  const toggleVideoSelection = (videoId: number) => {
    setSelectedVideoIds((currentSelection) => {
      const next = new Set(currentSelection);
      if (next.has(videoId)) {
        next.delete(videoId);
      } else {
        next.add(videoId);
      }
      return next;
    });
  };

  const clearSelection = () => setSelectedVideoIds(new Set());

  const publish = (body: ArchivePublishRequest) => {
    publishArchive.mutate(body, {
      onSuccess: (result) => {
        setLastResult(result);
      },
    });
  };

  const publishSelected = () => {
    const videoIds = [...selectedVideoIds];
    if (!videoIds.length) {
      return;
    }
    publish(baseRequest(defaults, { target: "selected_videos", videoIds }));
  };

  const publishCurrentFilters = () => {
    publish(
      baseRequest(defaults, {
        target: "current_filters",
        channelId: initialFilters.channelId,
        search: initialFilters.search,
      }),
    );
  };

  const publishNextEligible = () => {
    publish(
      baseRequest(defaults, {
        target: "next_eligible",
        channelId: initialFilters.channelId,
        search: initialFilters.search,
      }),
    );
  };

  const columns: ColumnDef<ArchiveOpsVideo>[] = [
    {
      id: "select",
      header: () => (
        <button
          aria-label={
            allVisibleSelected ? "Clear visible selection" : "Select visible videos"
          }
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
        return (
          <button
            aria-label={
              selected
                ? `Clear video ${row.original.videoId} selection`
                : `Select video ${row.original.videoId}`
            }
            className="inline-flex"
            onClick={() => toggleVideoSelection(row.original.videoId)}
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
        <div className="max-w-[420px]">
          <Link
            className="font-semibold text-slate-900 hover:underline"
            href={`/videos/${row.original.videoId}`}
          >
            {row.original.title}
          </Link>
          <div className="mt-1 flex flex-wrap gap-2 text-xs text-slate-500">
            <span>#{row.original.videoId}</span>
            <span>{compactId(row.original.youtubeVideoId)}</span>
            <span>{row.original.channelName}</span>
          </div>
        </div>
      ),
    },
    {
      header: "Timeline",
      cell: ({ row }) => (
        <div>
          <StatusBadge status={row.original.timelineReady ? "ready" : "not_ready"} />
          <div className="mt-1 text-xs text-slate-500">
            {row.original.timelineEpisodeCount} episodes
          </div>
        </div>
      ),
    },
    {
      header: "Artifact",
      cell: ({ row }) =>
        row.original.latestArtifact ? (
          <div className="max-w-[260px]">
            <StatusBadge status="published" />
            <div className="mt-1 truncate text-xs text-slate-500">
              {row.original.latestArtifact.version}
            </div>
            <a
              className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-teal-700 hover:underline"
              href={row.original.latestArtifact.publicUrl}
              rel="noreferrer"
              target="_blank"
            >
              <ExternalLink aria-hidden="true" size={13} />
              Open
            </a>
          </div>
        ) : (
          <StatusBadge status={row.original.timelineReady ? "ready" : "not_ready"} />
        ),
    },
    {
      header: "Task",
      cell: ({ row }) =>
        row.original.latestTask ? (
          <div>
            <StatusBadge status={row.original.latestTask.status} />
            <div className="mt-1 text-xs text-slate-500">
              task #{row.original.latestTask.videoTaskId}
            </div>
          </div>
        ) : (
          <span className="text-xs text-slate-500">-</span>
        ),
    },
    {
      header: "Updated",
      cell: ({ row }) =>
        formatDateTime(
          row.original.latestArtifact?.createdAt ?? row.original.latestTask?.updatedAt,
        ),
    },
    {
      header: "Actions",
      cell: ({ row }) => (
        <div className="flex flex-wrap gap-2">
          <Link className="ops-button" href={`/videos/${row.original.videoId}`}>
            Video detail
          </Link>
          {row.original.latestTask ? (
            <Link
              className="ops-button"
              href={logsHref({ videoTaskId: row.original.latestTask.videoTaskId })}
            >
              <ScrollText aria-hidden="true" size={15} />
              Logs
            </Link>
          ) : null}
          {row.original.latestTask?.jobId ? (
            <Link
              className="ops-button"
              href={`/jobs?step=archive_publish&subjectType=video&subjectId=${row.original.videoId}`}
            >
              Archive jobs
            </Link>
          ) : null}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Archive"
        description="Publish timeline-ready videos to R2 and inspect the current pointer/index state."
        actions={
          <Link className="ops-button" href="/tasks?taskName=archive_publish">
            <ListPlus aria-hidden="true" size={15} />
            Archive tasks
          </Link>
        }
      />
      <MetricStrip
        ariaLabel="Archive status"
        className="mb-4"
        items={[
          {
            label: "R2 config",
            value: current?.storage.configured ? "Configured" : "Missing",
            status: current?.storage.configured ? "succeeded" : "failed",
            meta: current?.storage.bucket ?? "Bucket not configured",
          },
          {
            label: "Pointer",
            value: current?.latestPublication?.version ?? "-",
            meta: current?.latestPublication?.pointerKey ?? "No pointer published",
          },
          {
            label: "Published videos",
            value: current?.latestPublication?.videoCount ?? 0,
            meta: current?.latestPublication
              ? formatDateTime(current.latestPublication.createdAt)
              : "No index",
          },
          {
            label: "Environment",
            value: environment,
            meta: current?.storage.publicBaseUrl ?? "Public base URL missing",
          },
        ]}
      />
      {currentLoading ? (
        <LoadingState className="mb-4" label="Loading archive status" />
      ) : null}
      {currentError ? <ErrorState className="mb-4" message={String(currentError)} /> : null}
      <ActionPanel
        className="mb-4"
        title="Publish archive"
        description="Publish selected videos, the current filter result, or the next eligible timeline-ready videos now."
        actions={
          <div className="flex flex-wrap gap-2">
            <button
              className="ops-button"
              disabled={pending || selectedVideoIds.size === 0}
              onClick={publishSelected}
              type="button"
            >
              <UploadCloud aria-hidden="true" size={15} />
              Publish selected
            </button>
            <button
              className="ops-button"
              disabled={pending}
              onClick={publishCurrentFilters}
              type="button"
            >
              Publish current filters
            </button>
            <button
              className="ops-button"
              disabled={pending}
              onClick={publishNextEligible}
              type="button"
            >
              Publish next eligible
            </button>
          </div>
        }
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          <label className="grid gap-1 text-xs font-semibold text-slate-600">
            Environment
            <input
              autoComplete="off"
              className="ops-input"
              name="archiveEnvironment"
              spellCheck={false}
              type="text"
              value={defaults.environment}
              onChange={(event) =>
                setDefaults((currentDefaults) => ({
                  ...currentDefaults,
                  environment: event.target.value.trim() || "prod",
                }))
              }
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-slate-600">
            Variant
            <input
              autoComplete="off"
              className="ops-input"
              name="archiveVariant"
              spellCheck={false}
              type="text"
              value={defaults.variant}
              onChange={(event) =>
                setDefaults((currentDefaults) => ({
                  ...currentDefaults,
                  variant: event.target.value.trim() || "control",
                }))
              }
            />
          </label>
          <label className="grid gap-1 text-xs font-semibold text-slate-600">
            Limit
            <select
              className="ops-input"
              name="archiveLimit"
              value={defaults.limit}
              onChange={(event) =>
                setDefaults((currentDefaults) => ({
                  ...currentDefaults,
                  limit: Number(event.target.value),
                }))
              }
            >
              <option value={20}>20 videos</option>
              <option value={50}>50 videos</option>
              <option value={100}>100 videos</option>
              <option value={200}>200 videos</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
            <input
              checked={defaults.retryFailed}
              name="archiveRetryFailed"
              onChange={(event) =>
                setDefaults((currentDefaults) => ({
                  ...currentDefaults,
                  retryFailed: event.target.checked,
                }))
              }
              type="checkbox"
            />
            Retry failed
          </label>
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-600">
            <input
              checked={defaults.regenerateSucceeded}
              name="archiveRegenerateSucceeded"
              onChange={(event) =>
                setDefaults((currentDefaults) => ({
                  ...currentDefaults,
                  regenerateSucceeded: event.target.checked,
                }))
              }
              type="checkbox"
            />
            Regenerate published
          </label>
          <button
            className="ops-button self-end"
            disabled={selectedVideoIds.size === 0}
            onClick={clearSelection}
            type="button"
          >
            <X aria-hidden="true" size={15} />
            Clear selection
          </button>
        </div>
        {publishArchive.error ? (
          <InlineNotice className="mt-3" tone="danger">
            {String(publishArchive.error)}
          </InlineNotice>
        ) : null}
        {lastResult ? (
          <ArchiveResultSummary className="mt-3" result={lastResult} />
        ) : null}
      </ActionPanel>
      <form
        key={JSON.stringify(initialFilters)}
        className="ops-panel mb-4 p-4"
        onSubmit={(event) => {
          event.preventDefault();
          router.push(archiveHref(formFilters(event.currentTarget)));
        }}
      >
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
          <ChannelFilterSelect
            channels={channelsData?.items ?? []}
            value={initialFilters.channelId}
            onChange={applySelectFilters}
          />
          <FilterSelect
            label="Publish status"
            name="publishStatus"
            defaultValue={initialFilters.publishStatus}
            onChange={applySelectFilters}
            options={PUBLISH_STATUS_OPTIONS}
          />
          <FilterInput
            label="Search"
            name="search"
            defaultValue={initialFilters.search}
            placeholder="Title, channel, YouTube ID"
          />
          <FilterInput
            label="Environment"
            name="environment"
            defaultValue={environment}
          />
          <FilterSelect
            label="Limit"
            name="limit"
            defaultValue={String(initialFilters.limit ?? 50)}
            onChange={applySelectFilters}
            options={[
              { value: "50", label: "50 rows" },
              { value: "100", label: "100 rows" },
              { value: "200", label: "200 rows" },
            ]}
          />
        </div>
        <FilterActions resetHref="/archive" />
      </form>
      {isLoading ? <LoadingState /> : null}
      {error ? <ErrorState message={String(error)} /> : null}
      <DataTable
        ariaLabel="Archive videos"
        columns={columns}
        data={videos}
        emptyLabel="No videos match the archive filters."
      />
      <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span>Total {data?.total ?? 0}</span>
        {initialFilters.offset ? (
          <Link
            className="ops-button"
            href={archiveHref({
              ...initialFilters,
              offset: Math.max(
                (initialFilters.offset ?? 0) - (initialFilters.limit ?? 50),
                0,
              ),
            })}
          >
            Newer
          </Link>
        ) : null}
        {(data?.total ?? 0) >
        (initialFilters.offset ?? 0) + (initialFilters.limit ?? 50) ? (
          <Link
            className="ops-button"
            href={archiveHref({
              ...initialFilters,
              offset: (initialFilters.offset ?? 0) + (initialFilters.limit ?? 50),
            })}
          >
            Older
          </Link>
        ) : null}
      </div>
    </>
  );
}

function ArchiveResultSummary({
  result,
  className = "",
}: {
  result: ArchivePublishResult;
  className?: string;
}) {
  return (
    <InlineNotice className={className} tone="success">
      <div className="grid gap-2 md:grid-cols-6">
        <span>Scanned {result.scannedCount}</span>
        <span>Processed {result.processedCount}</span>
        <span>Published {result.publishedCount}</span>
        <span>Already published {result.alreadyPublishedCount}</span>
        <span>Failed {result.failedCount + result.failedSkippedCount}</span>
        <span>Ineligible {result.ineligibleCount}</span>
      </div>
    </InlineNotice>
  );
}

function baseRequest(
  defaults: PublishDefaults,
  override: Partial<ArchivePublishRequest>,
): ArchivePublishRequest {
  return {
    target: "next_eligible",
    limit: defaults.limit,
    environment: defaults.environment || "prod",
    variant: defaults.variant || "control",
    schemaVersion: defaults.schemaVersion,
    retryFailed: defaults.retryFailed,
    regenerateSucceeded: defaults.regenerateSucceeded,
    ...override,
  };
}

function formFilters(form: HTMLFormElement): ArchiveOpsVideoFilters {
  const formData = new FormData(form);
  return {
    environment: stringFormValue(formData.get("environment")),
    channelId: positiveNumberFormValue(formData.get("channelId")),
    publishStatus: publishStatusFormValue(formData.get("publishStatus")),
    search: stringFormValue(formData.get("search")),
    limit: positiveNumberFormValue(formData.get("limit")) ?? 50,
  };
}

function archiveHref(filters: ArchiveOpsVideoFilters): string {
  return hrefWithQuery("/archive", filters);
}

function publishStatusFormValue(
  value: FormDataEntryValue | null,
): ArchiveOpsVideoFilters["publishStatus"] {
  const raw = stringFormValue(value);
  const allowed = new Set([
    "not_ready",
    "ready",
    "pending",
    "running",
    "failed",
    "published",
  ]);
  return raw && allowed.has(raw) ? (raw as ArchiveOpsVideoFilters["publishStatus"]) : undefined;
}
