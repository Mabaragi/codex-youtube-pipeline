import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChannelsPage } from "../channels-page";
import type {
  OpsChannel,
  OpsVideoTaskList,
  ResolveYouTubeChannelResult,
  Streamer,
} from "@/lib/types";

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
  streamers: {
    data: undefined as Streamer[] | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  collectVideos: {
    isPending: false,
    mutate: vi.fn(),
  },
  collectTranscripts: {
    isPending: false,
    mutate: vi.fn(),
  },
  createStreamer: {
    isPending: false,
    mutateAsync: vi.fn(),
  },
  resolveChannel: {
    isPending: false,
    mutateAsync: vi.fn(),
  },
}));

vi.mock("@/lib/queries", () => ({
  useCollectTranscriptsMutation: () => queryMocks.collectTranscripts,
  useCollectVideosMutation: () => queryMocks.collectVideos,
  useCreateStreamerMutation: () => queryMocks.createStreamer,
  useOpsChannels: () => queryMocks.channels,
  useResolveStreamerChannelMutation: () => queryMocks.resolveChannel,
  useRunningTranscriptTasks: () => queryMocks.runningTranscriptTasks,
  useStreamers: () => queryMocks.streamers,
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

const streamer: Streamer = {
  id: 1,
  name: "Streamer",
};

const createdStreamer: Streamer = {
  id: 2,
  name: "New Streamer",
};

const resolvedChannel: ResolveYouTubeChannelResult = {
  channelId: 1,
  streamerId: 1,
  handle: "@streamer",
  name: "Streamer Channel",
  youtubeChannelId: "UC123456789",
  uploadsPlaylistId: "UU123456789",
  sourceApiCallId: 1,
  jobId: 1,
  jobAttemptId: 1,
};

describe("ChannelsPage transcript collection state", () => {
  beforeEach(() => {
    queryMocks.channels.data = { items: [channel] };
    queryMocks.channels.isLoading = false;
    queryMocks.channels.error = null;
    queryMocks.streamers.data = [streamer];
    queryMocks.streamers.isLoading = false;
    queryMocks.streamers.error = null;
    queryMocks.runningTranscriptTasks.data = emptyRunningTasks;
    queryMocks.runningTranscriptTasks.isLoading = false;
    queryMocks.runningTranscriptTasks.isError = false;
    queryMocks.collectVideos.isPending = false;
    queryMocks.collectVideos.mutate.mockReset();
    queryMocks.collectTranscripts.isPending = false;
    queryMocks.collectTranscripts.mutate.mockReset();
    queryMocks.createStreamer.isPending = false;
    queryMocks.createStreamer.mutateAsync.mockReset();
    queryMocks.createStreamer.mutateAsync.mockResolvedValue(createdStreamer);
    queryMocks.resolveChannel.isPending = false;
    queryMocks.resolveChannel.mutateAsync.mockReset();
    queryMocks.resolveChannel.mutateAsync.mockResolvedValue(resolvedChannel);
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

  it("shows streamer suggestions for channel resolve", () => {
    render(<ChannelsPage />);

    const options = screen.getByTestId("streamer-options");

    expect(within(options).getByText("Streamer")).toBeTruthy();
  });

  it("creates a streamer from the compact add form", async () => {
    render(<ChannelsPage />);

    fireEvent.change(screen.getByLabelText("Streamer name"), {
      target: { value: "New Streamer" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add/i }));

    await waitFor(() => {
      expect(queryMocks.createStreamer.mutateAsync).toHaveBeenCalledWith({
        name: "New Streamer",
      });
    });
    expect(await screen.findByText("Added streamer New Streamer.")).toBeTruthy();
  });

  it("resolves a channel for an existing streamer without creating one", async () => {
    render(<ChannelsPage />);

    fireEvent.change(screen.getByLabelText("Streamer for resolve"), {
      target: { value: "Streamer" },
    });
    fireEvent.change(screen.getByLabelText("YouTube handle"), {
      target: { value: "@streamer" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Resolve/i }));

    await waitFor(() => {
      expect(queryMocks.resolveChannel.mutateAsync).toHaveBeenCalledWith({
        streamerId: 1,
        handle: "@streamer",
      });
    });
    expect(queryMocks.createStreamer.mutateAsync).not.toHaveBeenCalled();
  });

  it("creates a missing streamer before resolving a channel", async () => {
    queryMocks.resolveChannel.mutateAsync.mockResolvedValue({
      ...resolvedChannel,
      streamerId: 2,
      name: "New Streamer Channel",
    });
    render(<ChannelsPage />);

    fireEvent.change(screen.getByLabelText("Streamer for resolve"), {
      target: { value: "New Streamer" },
    });
    fireEvent.change(screen.getByLabelText("YouTube handle"), {
      target: { value: "@new-streamer" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Resolve/i }));

    await waitFor(() => {
      expect(queryMocks.createStreamer.mutateAsync).toHaveBeenCalledWith({
        name: "New Streamer",
      });
      expect(queryMocks.resolveChannel.mutateAsync).toHaveBeenCalledWith({
        streamerId: 2,
        handle: "@new-streamer",
      });
    });
    expect(
      await screen.findByText(
        /Added streamer New Streamer and resolved New Streamer Channel/i,
      ),
    ).toBeTruthy();
  });

  it("keeps resolve disabled until streamer name and handle are present", () => {
    render(<ChannelsPage />);

    const resolveButton = screen.getByRole("button", {
      name: /Resolve/i,
    }) as HTMLButtonElement;

    expect(resolveButton.disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Streamer for resolve"), {
      target: { value: "Streamer" },
    });

    expect(resolveButton.disabled).toBe(true);
  });

  it("shows resolve errors inline", async () => {
    queryMocks.resolveChannel.mutateAsync.mockRejectedValue(new Error("upstream failed"));
    render(<ChannelsPage />);

    fireEvent.change(screen.getByLabelText("Streamer for resolve"), {
      target: { value: "Streamer" },
    });
    fireEvent.change(screen.getByLabelText("YouTube handle"), {
      target: { value: "@streamer" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Resolve/i }));

    expect(await screen.findByText("Resolve failed: upstream failed")).toBeTruthy();
  });
});

function transcriptButton() {
  return screen.getByRole("button", {
    name: /Transcripts|Checking|Running/i,
  }) as HTMLButtonElement;
}
