import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VideosPage } from "../videos-page";
import type { OpsChannel, OpsVideoFilters, OpsVideoList } from "@/lib/types";

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
  videoFilters: undefined as OpsVideoFilters | undefined,
}));

vi.mock("@/lib/queries", () => ({
  useOpsChannels: () => queryMocks.channels,
  useOpsVideos: (filters: OpsVideoFilters) => {
    queryMocks.videoFilters = filters;
    return queryMocks.videos;
  },
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
    queryMocks.videoFilters = undefined;
  });

  it("links each row to the dedicated video detail page", () => {
    render(<VideosPage initialFilters={{ limit: 100, offset: 0 }} />);

    const link = screen.getByRole("link", { name: /Details/i });

    expect(link.getAttribute("href")).toBe("/videos/42");
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

  it("preserves an unknown selected channel option", () => {
    queryMocks.channels.data = { items: [] };

    render(<VideosPage initialFilters={{ channelId: 99, limit: 100, offset: 0 }} />);

    expect(screen.getByRole("option", { name: "#99" })).toBeTruthy();
  });
});
