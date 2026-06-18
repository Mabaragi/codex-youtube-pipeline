import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChannelsPage } from "../channels-page";
import type { OpsChannel, OpsVideoTaskList } from "@/lib/types";

const queryMocks = vi.hoisted(() => ({
  channels: {
    data: undefined as { items: OpsChannel[] } | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  runningTranscriptTasks: {
    data: undefined as OpsVideoTaskList | undefined,
    isLoading: false,
    isError: false,
  },
  collectVideos: {
    isPending: false,
    mutate: vi.fn(),
  },
  collectTranscripts: {
    isPending: false,
    mutate: vi.fn(),
  },
}));

vi.mock("@/lib/queries", () => ({
  useCollectTranscriptsMutation: () => queryMocks.collectTranscripts,
  useCollectVideosMutation: () => queryMocks.collectVideos,
  useOpsChannels: () => queryMocks.channels,
  useRunningTranscriptTasks: () => queryMocks.runningTranscriptTasks,
}));

const channel: OpsChannel = {
  channelId: 1,
  streamerId: 1,
  streamerName: "Streamer",
  handle: "@streamer",
  name: "Streamer Channel",
  youtubeChannelId: "UC123456789",
  uploadsPlaylistId: "UU123456789",
  videoCount: 5,
  transcriptSucceededCount: 2,
  taskFailedCount: 0,
  taskRunningCount: 0,
  latestVideoPublishedAt: "2026-06-18T00:00:00Z",
  latestTaskUpdatedAt: null,
};

const emptyRunningTasks: OpsVideoTaskList = {
  items: [],
  total: 0,
  limit: 1,
  offset: 0,
};

describe("ChannelsPage transcript collection state", () => {
  beforeEach(() => {
    queryMocks.channels.data = { items: [channel] };
    queryMocks.channels.isLoading = false;
    queryMocks.channels.error = null;
    queryMocks.runningTranscriptTasks.data = emptyRunningTasks;
    queryMocks.runningTranscriptTasks.isLoading = false;
    queryMocks.runningTranscriptTasks.isError = false;
    queryMocks.collectVideos.isPending = false;
    queryMocks.collectVideos.mutate.mockReset();
    queryMocks.collectTranscripts.isPending = false;
    queryMocks.collectTranscripts.mutate.mockReset();
  });

  it("disables transcript collection while checking running task state", () => {
    queryMocks.runningTranscriptTasks.data = undefined;
    queryMocks.runningTranscriptTasks.isLoading = true;

    render(<ChannelsPage />);

    expect(screen.getByText("Checking transcript task state...")).toBeTruthy();
    expect(transcriptButton().disabled).toBe(true);
  });

  it("disables transcript collection when any transcript task is running", () => {
    queryMocks.runningTranscriptTasks.data = {
      ...emptyRunningTasks,
      total: 1,
    };

    render(<ChannelsPage />);

    expect(
      screen.getByText(
        "Transcript collection is running; new collection is disabled until it finishes.",
      ),
    ).toBeTruthy();
    expect(transcriptButton().disabled).toBe(true);
  });

  it("disables transcript collection when running task state cannot be verified", () => {
    queryMocks.runningTranscriptTasks.data = undefined;
    queryMocks.runningTranscriptTasks.isError = true;

    render(<ChannelsPage />);

    expect(
      screen.getByText(
        "Cannot verify transcript task state. Collection is disabled to avoid duplicate runs.",
      ),
    ).toBeTruthy();
    expect(transcriptButton().disabled).toBe(true);
  });

  it("enables transcript collection when no transcript task is running", () => {
    render(<ChannelsPage />);

    expect(screen.queryByText("Checking transcript task state...")).toBeNull();
    expect(transcriptButton().disabled).toBe(false);
  });
});

function transcriptButton() {
  return screen.getByRole("button", {
    name: /Transcripts|Checking|Running/i,
  }) as HTMLButtonElement;
}
