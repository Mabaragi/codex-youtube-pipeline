import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OpsChannel, Streamer } from "@/lib/types";
import { ChannelsPage } from "../channels-page";

const mocks = vi.hoisted(() => ({
  ...(() => {
    const mutation = () => ({ isPending: false, mutate: vi.fn(), mutateAsync: vi.fn() });
    return {
      collectVideos: mutation(),
      collectAllTranscripts: mutation(),
      collectTranscripts: mutation(),
      generateAllCues: mutation(),
      generateCues: mutation(),
      createStreamer: mutation(),
      resolveChannel: mutation(),
    };
  })(),
  channels: { data: undefined as { items: OpsChannel[] } | undefined, isLoading: false, error: null as Error | null },
  streamers: { data: [] as Streamer[], isLoading: false, error: null as Error | null },
  collectTranscriptHook: vi.fn(),
  generateCueHook: vi.fn(),
}));

vi.mock("@/lib/queries", () => ({
  useOpsChannels: () => mocks.channels,
  useStreamers: () => mocks.streamers,
  useCollectVideosOperation: () => mocks.collectVideos,
  useCollectTranscriptsOperation: () => mocks.collectTranscriptHook(),
  useGenerateTranscriptCuesOperation: () => mocks.generateCueHook(),
  useCreateStreamerMutation: () => mocks.createStreamer,
  useResolveStreamerChannelMutation: () => mocks.resolveChannel,
}));

const channel: OpsChannel = {
  channelId: 7,
  streamerId: 1,
  streamerName: "Streamer",
  handle: "@channel",
  name: "Channel",
  youtubeChannelId: "UC123456789",
  uploadsPlaylistId: "UU123456789",
  videoCount: 2,
  transcriptSucceededCount: 1,
  taskNoTranscriptCount: 1,
  taskFailedCount: 1,
  taskRunningCount: 0,
  latestVideoPublishedAt: "2026-06-18T00:00:00Z",
  latestTaskUpdatedAt: null,
};

describe("ChannelsPage", () => {
  beforeEach(() => {
    mocks.channels.data = { items: [channel] };
    mocks.streamers.data = [{ id: 1, name: "Streamer" }];
    for (const item of [mocks.collectVideos, mocks.collectAllTranscripts, mocks.collectTranscripts, mocks.generateAllCues, mocks.generateCues]) {
      item.mutate.mockReset();
      item.isPending = false;
    }
    mocks.collectTranscriptHook.mockReset();
    mocks.collectTranscriptHook
      .mockReturnValueOnce(mocks.collectAllTranscripts)
      .mockReturnValueOnce(mocks.collectTranscripts);
    mocks.generateCueHook.mockReset();
    mocks.generateCueHook
      .mockReturnValueOnce(mocks.generateAllCues)
      .mockReturnValueOnce(mocks.generateCues);
  });

  it("collects channel videos through the unified operation", () => {
    render(<ChannelsPage />);
    fireEvent.click(screen.getByRole("button", { name: "Videos" }));
    expect(mocks.collectVideos.mutate).toHaveBeenCalledWith({
      channelIds: [7], retryFailed: false, rerunSucceeded: true, timeoutSeconds: 600,
    });
  });

  it("submits transcript work with a channel selection", () => {
    render(<ChannelsPage />);
    fireEvent.click(screen.getByRole("button", { name: "Transcripts" }));
    expect(mocks.collectTranscripts.mutate).toHaveBeenCalledWith(expect.objectContaining({
      selection: { type: "channel", channelId: 7, limit: 2 },
      retryFailed: false,
      recheckNoTranscript: false,
    }));
  });
});
