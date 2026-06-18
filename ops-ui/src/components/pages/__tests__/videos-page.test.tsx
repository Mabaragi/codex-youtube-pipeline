import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VideosPage } from "../videos-page";
import type { OpsVideoList } from "@/lib/types";

const queryMocks = vi.hoisted(() => ({
  videos: {
    data: undefined as OpsVideoList | undefined,
    isLoading: false,
    error: null as Error | null,
  },
}));

vi.mock("@/lib/queries", () => ({
  useOpsVideos: () => queryMocks.videos,
}));

vi.mock("@/store/use-ops-store", () => ({
  useOpsStore: () => ({
    videoSearch: "",
    videoTaskStatus: "",
    setVideoSearch: vi.fn(),
    setVideoTaskStatus: vi.fn(),
  }),
}));

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
    queryMocks.videos.data = videoList;
    queryMocks.videos.isLoading = false;
    queryMocks.videos.error = null;
  });

  it("links each row to the dedicated video detail page", () => {
    render(<VideosPage />);

    const link = screen.getByRole("link", { name: /Details/i });

    expect(link.getAttribute("href")).toBe("/videos/42");
  });
});
