import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VideosPage } from "../videos-page";
import type {
  MicroEventBatchExtractResult,
  MicroEventEnqueueResult,
  OpsChannel,
  OpsVideoFilters,
  OpsVideoList,
  PromptDetail,
  TimelineComposeEnqueueResult,
} from "@/lib/types";

const routerPush = vi.hoisted(() => vi.fn());
const queryMocks = vi.hoisted(() => ({
  channels: {
    data: undefined as { items: OpsChannel[] } | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  videos: {
    data: undefined as OpsVideoList | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  extractAllMicroEvents: {
    mutate: vi.fn(),
    isPending: false,
    data: undefined as MicroEventBatchExtractResult | undefined,
    error: null as Error | null,
  },
  enqueueMicroEvents: {
    mutate: vi.fn(),
    isPending: false,
    data: undefined as MicroEventEnqueueResult | undefined,
    error: null as Error | null,
  },
  enqueueTimelineCompose: {
    mutate: vi.fn(),
    isPending: false,
    data: undefined as TimelineComposeEnqueueResult | undefined,
    error: null as Error | null,
  },
  promptDetails: {} as Record<
    string,
    { data: PromptDetail | undefined; isLoading: boolean; error: Error | null }
  >,
  videoFilters: undefined as OpsVideoFilters | undefined,
}));

vi.mock("@/lib/queries", () => ({
  useEnqueueMicroEventsMutation: () => queryMocks.enqueueMicroEvents,
  useEnqueueTimelineComposeMutation: () => queryMocks.enqueueTimelineCompose,
  useExtractAllMicroEventsMutation: () => queryMocks.extractAllMicroEvents,
  useOpsChannels: () => queryMocks.channels,
  useOpsVideos: (filters: OpsVideoFilters) => {
    queryMocks.videoFilters = filters;
    return queryMocks.videos;
  },
  usePromptDetail: (promptKey: string) => queryMocks.promptDetails[promptKey],
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
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

const videoList: OpsVideoList = {
  total: 1,
  limit: 100,
  offset: 0,
  items: [
    {
      videoId: 42,
      channelId: 7,
      channelName: "Channel",
      youtubeVideoId: "abc123DEF45",
      title: "Stored video",
      publishedAt: "2026-06-18T00:00:00Z",
      duration: "PT1M",
      thumbnailUrl: null,
      latestTaskId: 9,
      latestTaskName: "transcript_collect",
      latestTaskStatus: "succeeded",
      latestTaskUpdatedAt: "2026-06-18T01:00:00Z",
      transcriptId: 11,
      generation: {
        cues: {
          generated: true,
          transcriptId: 11,
          cueCount: 24,
          latestTaskId: 10,
          latestTaskStatus: "succeeded",
          latestTaskUpdatedAt: "2026-06-18T01:05:00Z",
        },
        microEvents: {
          generated: true,
          videoTaskId: 12,
          windowCount: 3,
          microEventCount: 8,
          latestTaskId: 12,
          latestTaskStatus: "succeeded",
          latestTaskUpdatedAt: "2026-06-18T01:15:00Z",
        },
        timeline: {
          generated: false,
          compositionId: null,
          videoTaskId: null,
          episodeCount: 0,
          latestTaskId: 13,
          latestTaskStatus: "running",
          latestTaskUpdatedAt: "2026-06-18T01:20:00Z",
        },
      },
    },
  ],
};

const microEventPromptDetail: PromptDetail = {
  key: "micro_event_extract",
  active: {
    key: "micro_event_extract",
    versionId: 101,
    versionLabel: "micro-active",
    body: "micro prompt",
    bodySha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    source: "database",
  },
  versions: [
    {
      id: 101,
      promptKey: "micro_event_extract",
      versionLabel: "micro-active",
      status: "PUBLISHED",
      isActive: true,
      bodySha256: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      sourceNote: null,
      publishedAt: "2026-06-18T00:00:00Z",
      archivedAt: null,
      createdAt: "2026-06-18T00:00:00Z",
      updatedAt: "2026-06-18T00:00:00Z",
    },
    {
      id: 102,
      promptKey: "micro_event_extract",
      versionLabel: "micro-candidate",
      status: "PUBLISHED",
      isActive: false,
      bodySha256: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      sourceNote: null,
      publishedAt: "2026-06-18T00:00:00Z",
      archivedAt: null,
      createdAt: "2026-06-18T00:00:00Z",
      updatedAt: "2026-06-18T00:00:00Z",
    },
  ],
};

const timelinePromptDetail: PromptDetail = {
  key: "timeline_compose",
  active: {
    key: "timeline_compose",
    versionId: 201,
    versionLabel: "timeline-active",
    body: "timeline prompt",
    bodySha256: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    source: "database",
  },
  versions: [
    {
      id: 201,
      promptKey: "timeline_compose",
      versionLabel: "timeline-active",
      status: "PUBLISHED",
      isActive: true,
      bodySha256: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
      sourceNote: null,
      publishedAt: "2026-06-18T00:00:00Z",
      archivedAt: null,
      createdAt: "2026-06-18T00:00:00Z",
      updatedAt: "2026-06-18T00:00:00Z",
    },
    {
      id: 202,
      promptKey: "timeline_compose",
      versionLabel: "timeline-candidate",
      status: "PUBLISHED",
      isActive: false,
      bodySha256: "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      sourceNote: null,
      publishedAt: "2026-06-18T00:00:00Z",
      archivedAt: null,
      createdAt: "2026-06-18T00:00:00Z",
      updatedAt: "2026-06-18T00:00:00Z",
    },
  ],
};

describe("VideosPage", () => {
  beforeEach(() => {
    routerPush.mockReset();
    queryMocks.channels.data = { items: [channel] };
    queryMocks.videos.data = videoList;
    queryMocks.videos.isLoading = false;
    queryMocks.videos.error = null;
    queryMocks.extractAllMicroEvents.mutate.mockReset();
    queryMocks.extractAllMicroEvents.isPending = false;
    queryMocks.extractAllMicroEvents.data = undefined;
    queryMocks.extractAllMicroEvents.error = null;
    queryMocks.enqueueMicroEvents.mutate.mockReset();
    queryMocks.enqueueMicroEvents.isPending = false;
    queryMocks.enqueueMicroEvents.data = undefined;
    queryMocks.enqueueMicroEvents.error = null;
    queryMocks.enqueueTimelineCompose.mutate.mockReset();
    queryMocks.enqueueTimelineCompose.isPending = false;
    queryMocks.enqueueTimelineCompose.data = undefined;
    queryMocks.enqueueTimelineCompose.error = null;
    queryMocks.promptDetails = {
      micro_event_extract: {
        data: microEventPromptDetail,
        isLoading: false,
        error: null,
      },
      timeline_compose: {
        data: timelinePromptDetail,
        isLoading: false,
        error: null,
      },
    };
    queryMocks.videoFilters = undefined;
  });

  it("links each row to the dedicated video detail page", () => {
    render(<VideosPage initialFilters={{ limit: 100, offset: 0 }} />);

    const link = screen.getByRole("link", { name: /Details/i });

    expect(link.getAttribute("href")).toBe("/videos/42");
  });

  it("shows generation status for cues, micro-events, and timeline", () => {
    render(<VideosPage initialFilters={{ limit: 100, offset: 0 }} />);

    expect(screen.getByText("Cues")).toBeTruthy();
    expect(screen.getByText("24 cues, transcript #11")).toBeTruthy();
    expect(screen.getByText("Micro")).toBeTruthy();
    expect(screen.getByText("8 events, 3 windows")).toBeTruthy();
    expect(screen.getByText("task #13")).toBeTruthy();
    expect(
      screen.getByLabelText("Timeline generation running"),
    ).toBeTruthy();
  });

  it("passes initial URL filters to the videos query", () => {
    render(
      <VideosPage
        initialFilters={{
          channelId: 7,
          search: "Stored",
          taskStatus: "failed",
          limit: 100,
          offset: 0,
        }}
      />,
    );

    expect(queryMocks.videoFilters).toEqual({
      channelId: 7,
      search: "Stored",
      taskStatus: "failed",
      limit: 100,
      offset: 0,
    });
  });

  it("submits filters through the videos route", () => {
    render(<VideosPage initialFilters={{ limit: 100, offset: 0 }} />);

    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "needle" } });
    fireEvent.change(screen.getByLabelText("Task status"), {
      target: { value: "running" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Apply/i }));

    expect(routerPush).toHaveBeenCalledWith(
      "/videos?channelId=7&search=needle&taskStatus=running&limit=100",
    );
    expect(screen.getByRole("link", { name: /Reset/i }).getAttribute("href")).toBe(
      "/videos",
    );
  });

  it("applies channel and task filters as soon as they are selected", () => {
    render(<VideosPage initialFilters={{ limit: 100, offset: 0 }} />);

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "needle" } });
    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "7" } });

    expect(routerPush).toHaveBeenLastCalledWith(
      "/videos?channelId=7&search=needle&limit=100",
    );

    fireEvent.change(screen.getByLabelText("Task status"), {
      target: { value: "running" },
    });

    expect(routerPush).toHaveBeenLastCalledWith(
      "/videos?channelId=7&search=needle&taskStatus=running&limit=100",
    );
  });

  it("preserves an unknown selected channel option", () => {
    queryMocks.channels.data = { items: [] };

    render(<VideosPage initialFilters={{ channelId: 99, limit: 100, offset: 0 }} />);

    expect(screen.getByRole("option", { name: "#99" })).toBeTruthy();
  });

  it("queues selected videos with selected options", () => {
    render(<VideosPage initialFilters={{ limit: 100, offset: 0 }} />);

    fireEvent.click(screen.getByRole("button", { name: /Select video 42/i }));
    fireEvent.change(screen.getAllByLabelText("Model")[0], {
      target: { value: "gpt-5.4" },
    });
    fireEvent.change(screen.getAllByLabelText("Reasoning")[0], {
      target: { value: "high" },
    });
    fireEvent.change(screen.getAllByLabelText("Prompt")[0], {
      target: { value: "102" },
    });
    fireEvent.click(screen.getAllByLabelText("Retry failed")[0]);
    fireEvent.click(screen.getAllByRole("button", { name: /Queue selected/i })[0]);

    expect(queryMocks.enqueueMicroEvents.mutate).toHaveBeenCalledWith({
      target: "selected_videos",
      videoIds: [42],
      limit: 1,
      model: "gpt-5.4",
      reasoningEffort: "high",
      retryFailed: true,
      regenerateSucceeded: false,
      windowMinutes: 30,
      overlapMinutes: 5,
      promptVersionId: 102,
    });
  });

  it("runs a micro-event batch now with selected options", () => {
    render(<VideosPage initialFilters={{ limit: 100, offset: 0 }} />);

    fireEvent.change(screen.getAllByLabelText("Batch size")[0], {
      target: { value: "3" },
    });
    fireEvent.change(screen.getAllByLabelText("Model")[0], {
      target: { value: "gpt-5.4" },
    });
    fireEvent.change(screen.getAllByLabelText("Reasoning")[0], {
      target: { value: "high" },
    });
    fireEvent.change(screen.getAllByLabelText("Prompt")[0], {
      target: { value: "102" },
    });
    fireEvent.click(screen.getAllByLabelText("Retry failed")[0]);
    fireEvent.click(screen.getByRole("button", { name: /Run now/i }));

    expect(queryMocks.extractAllMicroEvents.mutate).toHaveBeenCalledWith({
      limit: 3,
      model: "gpt-5.4",
      reasoningEffort: "high",
      retryFailed: true,
      regenerateSucceeded: false,
      windowMinutes: 30,
      overlapMinutes: 5,
      promptVersionId: 102,
    });
  });

  it("queues current filters using the active video filters", () => {
    render(
      <VideosPage
        initialFilters={{
          channelId: 7,
          search: "Stored",
          taskStatus: "succeeded",
          limit: 100,
          offset: 0,
        }}
      />,
    );

    fireEvent.click(screen.getAllByRole("button", { name: /Queue current filters/i })[0]);

    expect(queryMocks.enqueueMicroEvents.mutate).toHaveBeenCalledWith({
      target: "current_filters",
      channelId: 7,
      search: "Stored",
      taskStatus: "succeeded",
      limit: 20,
      model: "gpt-5.5",
      reasoningEffort: "medium",
      retryFailed: false,
      regenerateSucceeded: false,
      windowMinutes: 30,
      overlapMinutes: 5,
    });
  });

  it("queues timeline compose for selected videos", () => {
    render(<VideosPage initialFilters={{ limit: 100, offset: 0 }} />);

    fireEvent.click(screen.getByRole("button", { name: /Select video 42/i }));
    fireEvent.change(screen.getAllByLabelText("Batch size")[1], {
      target: { value: "3" },
    });
    fireEvent.change(screen.getAllByLabelText("Model")[1], {
      target: { value: "gpt-5.4-mini" },
    });
    fireEvent.change(screen.getAllByLabelText("Reasoning")[1], {
      target: { value: "low" },
    });
    fireEvent.change(screen.getAllByLabelText("Prompt")[1], {
      target: { value: "202" },
    });
    fireEvent.click(screen.getAllByLabelText("Retry failed")[1]);
    fireEvent.click(screen.getAllByRole("button", { name: /Queue selected/i })[1]);

    expect(queryMocks.enqueueTimelineCompose.mutate).toHaveBeenCalledWith({
      target: "selected_videos",
      videoIds: [42],
      limit: 1,
      model: "gpt-5.4-mini",
      reasoningEffort: "low",
      retryFailed: true,
      regenerateSucceeded: false,
      copyStyle: "LIGHT_FANDOM_V1",
      promptVersionId: 202,
    });
  });

  it("shows micro-event batch result counts and task link", () => {
    queryMocks.extractAllMicroEvents.data = {
      requestedCount: 1,
      processedCount: 1,
      succeededCount: 1,
      failedCount: 0,
      skippedCount: 0,
      timedOutCount: 0,
      scannedCount: 2,
      alreadySatisfiedCount: 1,
      ineligibleCount: 0,
      items: [
        {
          videoId: 42,
          youtubeVideoId: "abc123DEF45",
          videoTaskId: 99,
          status: "succeeded",
          reason: "extracted",
          model: "gpt-5.4",
          reasoningEffort: "high",
          jobId: 77,
          jobAttemptId: 88,
          transcriptId: 11,
          windowCount: 1,
          microEventCount: 2,
          asrCorrectionCandidateCount: 0,
          firstCueId: "tr1-c000001",
          lastCueId: "tr1-c000002",
          errorType: null,
          errorMessage: null,
        },
      ],
    };

    render(<VideosPage initialFilters={{ limit: 100, offset: 0 }} />);

    expect(screen.getByText("Processed")).toBeTruthy();
    expect(screen.getByText("Satisfied")).toBeTruthy();
    expect(screen.getByText("extracted")).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /Tasks/i })[0].getAttribute("href")).toBe(
      "/tasks?taskName=micro_event_extract&limit=100",
    );
  });
});
