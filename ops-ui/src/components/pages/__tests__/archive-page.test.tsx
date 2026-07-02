import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ArchivePage } from "../archive-page";
import type {
  ArchiveCurrent,
  ArchiveOpsVideoFilters,
  ArchiveOpsVideoList,
  ArchivePublishResult,
  OpsChannel,
} from "@/lib/types";

const routerPush = vi.hoisted(() => vi.fn());
const queryMocks = vi.hoisted(() => ({
  channels: {
    data: undefined as { items: OpsChannel[] } | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  current: {
    data: undefined as ArchiveCurrent | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  videos: {
    data: undefined as ArchiveOpsVideoList | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  archiveFilters: undefined as ArchiveOpsVideoFilters | undefined,
  publishArchive: {
    mutate: vi.fn(),
    isPending: false,
    error: null as Error | null,
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("@/lib/queries", () => ({
  useArchiveCurrent: () => queryMocks.current,
  useArchiveVideos: (filters: ArchiveOpsVideoFilters) => {
    queryMocks.archiveFilters = filters;
    return queryMocks.videos;
  },
  useOpsChannels: () => queryMocks.channels,
  usePublishArchiveMutation: () => queryMocks.publishArchive,
}));

const channel: OpsChannel = {
  channelId: 7,
  streamerId: 1,
  streamerName: "Streamer",
  handle: "@channel",
  name: "Channel",
  youtubeChannelId: "UC123456789",
  uploadsPlaylistId: "UU123456789",
  videoCount: 1,
  transcriptSucceededCount: 1,
  taskNoTranscriptCount: 0,
  taskFailedCount: 0,
  taskRunningCount: 0,
  latestVideoPublishedAt: "2026-06-18T00:00:00Z",
  latestTaskUpdatedAt: null,
};

const current: ArchiveCurrent = {
  publishMode: "prod",
  environment: "prod",
  storage: {
    configured: true,
    bucket: "vod-archive",
    endpoint: "https://account.r2.cloudflarestorage.com",
    publicBaseUrl: "https://pub.example.dev",
    prefix: "archive",
  },
  latestPublication: {
    publicationId: 3,
    environment: "prod",
    schemaVersion: 1,
    version: "20260627T120000Z",
    pointerKey: "archive/channels/prod.json",
    indexKey: "archive/archive/v1/index.20260627T120000Z.json",
    publicUrl: "https://pub.example.dev/archive/archive/v1/index.20260627T120000Z.json",
    sha256: "a".repeat(64),
    byteSize: 123,
    videoCount: 1,
    createdAt: "2026-06-27T12:00:00Z",
  },
};

const videoList: ArchiveOpsVideoList = {
  total: 1,
  limit: 50,
  offset: 0,
  items: [
    {
      videoId: 71,
      channelId: 7,
      channelName: "Channel",
      youtubeVideoId: "JSbJMOXtqn8",
      title: "Timeline-ready video",
      publishedAt: "2026-06-22T00:00:00Z",
      duration: "PT1H",
      thumbnailUrl: null,
      timelineReady: true,
      timelineCompositionId: 9,
      timelineTaskId: 33,
      timelineEpisodeCount: 34,
      latestTask: null,
      latestArtifact: null,
    },
  ],
};

describe("ArchivePage", () => {
  beforeEach(() => {
    routerPush.mockReset();
    queryMocks.channels.data = { items: [channel] };
    queryMocks.current.data = current;
    queryMocks.current.isLoading = false;
    queryMocks.current.error = null;
    queryMocks.videos.data = videoList;
    queryMocks.videos.isLoading = false;
    queryMocks.videos.error = null;
    queryMocks.archiveFilters = undefined;
    queryMocks.publishArchive.mutate.mockReset();
    queryMocks.publishArchive.isPending = false;
    queryMocks.publishArchive.error = null;
  });

  it("passes initial filters to the archive videos query", () => {
    render(
      <ArchivePage
        initialFilters={{
          environment: "prod",
          channelId: 7,
          publishStatus: "ready",
          limit: 50,
          offset: 0,
        }}
      />,
    );

    expect(queryMocks.archiveFilters).toEqual({
      environment: "prod",
      channelId: 7,
      publishStatus: "ready",
      limit: 50,
      offset: 0,
    });
  });

  it("publishes selected videos through the archive publish mutation", () => {
    render(<ArchivePage initialFilters={{ environment: "prod", limit: 50, offset: 0 }} />);

    fireEvent.click(screen.getByRole("button", { name: /Select video 71/i }));
    fireEvent.click(screen.getByRole("button", { name: /Publish selected/i }));

    expect(queryMocks.publishArchive.mutate).toHaveBeenCalledWith(
      {
        target: "selected_videos",
        videoIds: [71],
        limit: 20,
        publishMode: "prod",
        environment: "prod",
        variant: "control",
        schemaVersion: 1,
        retryFailed: false,
        regenerateSucceeded: false,
      },
      expect.objectContaining({ onSuccess: expect.any(Function) }),
    );
  });

  it("renders publish result summaries", () => {
    const result: ArchivePublishResult = {
      requestedCount: 1,
      scannedCount: 1,
      processedCount: 1,
      publishedCount: 1,
      alreadyPublishedCount: 0,
      regeneratedCount: 0,
      failedCount: 0,
      failedSkippedCount: 0,
      ineligibleCount: 0,
      items: [],
    };
    queryMocks.publishArchive.mutate.mockImplementation((_body, options) => {
      options?.onSuccess?.(result);
    });

    render(<ArchivePage initialFilters={{ environment: "prod", limit: 50, offset: 0 }} />);

    fireEvent.click(screen.getByRole("button", { name: /Publish next eligible/i }));

    expect(screen.getByText("Published 1")).toBeTruthy();
  });
});
