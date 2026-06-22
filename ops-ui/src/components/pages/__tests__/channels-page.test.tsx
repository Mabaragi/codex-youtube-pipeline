import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChannelsPage } from "../channels-page";
import type {
  OpsChannel,
  OpsVideoTaskList,
  PipelineJobList,
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
  runningTranscriptBatches: {
    data: undefined as PipelineJobList | undefined,
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
  collectAllTranscripts: {
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
  useCollectAllTranscriptsMutation: () => queryMocks.collectAllTranscripts,
  useCollectTranscriptsMutation: () => queryMocks.collectTranscripts,
  useCollectVideosMutation: () => queryMocks.collectVideos,
  useCreateStreamerMutation: () => queryMocks.createStreamer,
  useOpsChannels: () => queryMocks.channels,
  useResolveStreamerChannelMutation: () => queryMocks.resolveChannel,
  useRunningTranscriptBatches: () => queryMocks.runningTranscriptBatches,
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
  taskNoTranscriptCount: 1,
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

const emptyRunningBatches: PipelineJobList = {
  items: [],
  nextCursor: null,
};

const runningBatch: PipelineJobList["items"][number] = {
  jobId: 44,
  step: "transcript_collect_batch",
  status: "running",
  subjectType: "channel",
  subjectId: 1,
  externalKey: null,
  createdAt: "2026-06-18T00:00:00Z",
  updatedAt: "2026-06-18T00:00:00Z",
  completedAt: null,
  latestAttemptId: 45,
  latestAttemptStatus: "running",
  attemptCount: 1,
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
    queryMocks.runningTranscriptBatches.data = emptyRunningBatches;
    queryMocks.runningTranscriptBatches.isLoading = false;
    queryMocks.runningTranscriptBatches.isError = false;
    queryMocks.collectVideos.isPending = false;
    queryMocks.collectVideos.mutate.mockReset();
    queryMocks.collectAllTranscripts.isPending = false;
    queryMocks.collectAllTranscripts.mutate.mockReset();
    queryMocks.collectTranscripts.isPending = false;
    queryMocks.collectTranscripts.mutate.mockReset();
    queryMocks.createStreamer.isPending = false;
    queryMocks.createStreamer.mutateAsync.mockReset();
    queryMocks.createStreamer.mutateAsync.mockResolvedValue(createdStreamer);
    queryMocks.resolveChannel.isPending = false;
    queryMocks.resolveChannel.mutateAsync.mockReset();
    queryMocks.resolveChannel.mutateAsync.mockResolvedValue(resolvedChannel);
  });

  it("disables transcript collection while checking running collection state", () => {
    queryMocks.runningTranscriptTasks.data = undefined;
    queryMocks.runningTranscriptTasks.isLoading = true;

    render(<ChannelsPage />);

    expect(screen.getByText("Checking transcript collection state...")).toBeTruthy();
    expect(transcriptButton().disabled).toBe(true);
    expect(allTranscriptButton().disabled).toBe(true);
  });

  it("disables transcript collection when any transcript task is running", () => {
    queryMocks.runningTranscriptTasks.data = {
      ...emptyRunningTasks,
      total: 1,
    };

    render(<ChannelsPage />);

    expect(
      screen.getByText(
        "Transcript collection is running. Transcript actions are disabled.",
      ),
    ).toBeTruthy();
    expect(transcriptButton().disabled).toBe(true);
    expect(allTranscriptButton().disabled).toBe(true);
  });

  it("disables transcript collection when a transcript batch is running", () => {
    queryMocks.runningTranscriptBatches.data = {
      items: [runningBatch],
      nextCursor: null,
    };

    render(<ChannelsPage />);

    expect(
      screen.getByText(
        "Transcript collection is running. Transcript actions are disabled.",
      ),
    ).toBeTruthy();
    expect(transcriptButton().disabled).toBe(true);
    expect(allTranscriptButton().disabled).toBe(true);
  });

  it("disables transcript collection when running collection state cannot be verified", () => {
    queryMocks.runningTranscriptTasks.data = undefined;
    queryMocks.runningTranscriptTasks.isError = true;

    render(<ChannelsPage />);

    expect(
      screen.getByText(
        "Cannot verify transcript collection state. Transcript actions are disabled.",
      ),
    ).toBeTruthy();
    expect(transcriptButton().disabled).toBe(true);
    expect(allTranscriptButton().disabled).toBe(true);
  });

  it("enables transcript collection when no transcript task is running", () => {
    render(<ChannelsPage />);

    expect(screen.queryByText("Checking transcript collection state...")).toBeNull();
    expect(transcriptButton().disabled).toBe(false);
    expect(allTranscriptButton().disabled).toBe(false);
  });

  it("collects transcripts for all stored videos", () => {
    queryMocks.channels.data = {
      items: [
        { ...channel, channelId: 1, videoCount: 42 },
        { ...channel, channelId: 2, handle: "@other", name: "Other", videoCount: 8 },
      ],
    };
    render(<ChannelsPage />);

    fireEvent.click(allTranscriptButton());

    expect(queryMocks.collectAllTranscripts.mutate).toHaveBeenCalledTimes(1);
    expect(queryMocks.collectAllTranscripts.mutate).toHaveBeenCalledWith({});
  });

  it("retries failed transcript tasks for all channels", () => {
    queryMocks.channels.data = {
      items: [
        { ...channel, channelId: 1, taskFailedCount: 2 },
        { ...channel, channelId: 2, handle: "@other", name: "Other", taskFailedCount: 1 },
      ],
    };
    render(<ChannelsPage />);

    fireEvent.click(
      screen.getByRole("button", { name: /Retry failed for all channels/i }),
    );

    expect(queryMocks.collectAllTranscripts.mutate).toHaveBeenCalledWith({
      collectNew: false,
      retryFailed: true,
    });
  });

  it("rechecks no-transcript tasks for all channels", () => {
    render(<ChannelsPage />);

    fireEvent.click(
      screen.getByRole("button", {
        name: /Recheck no transcript for all channels/i,
      }),
    );

    expect(queryMocks.collectAllTranscripts.mutate).toHaveBeenCalledWith({
      collectNew: false,
      recheckNoTranscript: true,
    });
  });

  it("collects transcripts for all stored channel videos", () => {
    queryMocks.channels.data = { items: [{ ...channel, videoCount: 42 }] };
    render(<ChannelsPage />);

    fireEvent.click(transcriptButton());

    expect(queryMocks.collectTranscripts.mutate).toHaveBeenCalledWith({
      channelId: 1,
      limit: 42,
    });
  });

  it("retries failed transcript tasks for one channel", () => {
    queryMocks.channels.data = {
      items: [{ ...channel, taskFailedCount: 2, videoCount: 42 }],
    };
    render(<ChannelsPage />);

    fireEvent.click(
      screen.getByRole("button", { name: /Retry failed for Streamer Channel/i }),
    );

    expect(queryMocks.collectTranscripts.mutate).toHaveBeenCalledWith({
      channelId: 1,
      collectNew: false,
      limit: 42,
      retryFailed: true,
    });
  });

  it("rechecks no-transcript tasks for one channel", () => {
    queryMocks.channels.data = {
      items: [{ ...channel, taskNoTranscriptCount: 2, videoCount: 42 }],
    };
    render(<ChannelsPage />);

    fireEvent.click(
      screen.getByRole("button", {
        name: /Recheck no transcript for Streamer Channel/i,
      }),
    );

    expect(queryMocks.collectTranscripts.mutate).toHaveBeenCalledWith({
      channelId: 1,
      collectNew: false,
      limit: 42,
      recheckNoTranscript: true,
    });
  });

  it("disables transcript collection when a channel has no stored videos", () => {
    queryMocks.channels.data = { items: [{ ...channel, videoCount: 0 }] };
    render(<ChannelsPage />);

    const button = transcriptButton();
    const globalButton = allTranscriptButton();

    expect(button.disabled).toBe(true);
    expect(button.title).toBe("No stored videos to collect transcripts for");
    expect(globalButton.disabled).toBe(true);
    expect(globalButton.title).toBe("No stored videos to collect transcripts for");
  });

  it("disables transcript actions while global transcript collection is pending", () => {
    queryMocks.collectAllTranscripts.isPending = true;
    render(<ChannelsPage />);

    expect(allTranscriptButton().disabled).toBe(true);
    expect(transcriptButton().disabled).toBe(true);
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
    name: /^(Transcripts|Checking|Running|Blocked)$/i,
  }) as HTMLButtonElement;
}

function allTranscriptButton() {
  return screen.getByRole("button", {
    name: /All transcripts/i,
  }) as HTMLButtonElement;
}
