import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TasksPage } from "../tasks-page";
import type {
  OpsChannel,
  OpsVideoTaskFilters,
  OpsVideoTaskList,
  PipelineJobList,
} from "@/lib/types";

const routerPush = vi.hoisted(() => vi.fn());
const queryMocks = vi.hoisted(() => ({
  channels: {
    data: undefined as { items: OpsChannel[] } | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  tasks: {
    data: undefined as OpsVideoTaskList | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  taskFilters: undefined as OpsVideoTaskFilters | undefined,
  retryJob: {
    isPending: false,
    mutate: vi.fn(),
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
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("@/lib/queries", () => ({
  useOpsChannels: () => queryMocks.channels,
  useOpsVideoTasks: (filters: OpsVideoTaskFilters) => {
    queryMocks.taskFilters = filters;
    return queryMocks.tasks;
  },
  useRetryJobMutation: () => queryMocks.retryJob,
  useRunningTranscriptBatches: () => queryMocks.runningTranscriptBatches,
  useRunningTranscriptTasks: () => queryMocks.runningTranscriptTasks,
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
  subjectType: "all_videos",
  subjectId: null,
  externalKey: null,
  createdAt: "2026-06-18T00:00:00Z",
  updatedAt: "2026-06-18T00:00:00Z",
  completedAt: null,
  latestAttemptId: 45,
  latestAttemptStatus: "running",
  attemptCount: 1,
};

describe("TasksPage filters", () => {
  beforeEach(() => {
    routerPush.mockReset();
    queryMocks.channels.data = { items: [channel] };
    queryMocks.tasks.data = { items: [], total: 0, limit: 100, offset: 0 };
    queryMocks.tasks.isLoading = false;
    queryMocks.tasks.error = null;
    queryMocks.taskFilters = undefined;
    queryMocks.retryJob.isPending = false;
    queryMocks.retryJob.mutate.mockReset();
    queryMocks.runningTranscriptTasks.data = emptyRunningTasks;
    queryMocks.runningTranscriptTasks.isLoading = false;
    queryMocks.runningTranscriptTasks.isError = false;
    queryMocks.runningTranscriptBatches.data = emptyRunningBatches;
    queryMocks.runningTranscriptBatches.isLoading = false;
    queryMocks.runningTranscriptBatches.isError = false;
  });

  it("passes initial URL filters to the tasks query", () => {
    render(
      <TasksPage
        initialFilters={{
          channelId: 7,
          status: "failed",
          taskName: "transcript_collect",
          limit: 100,
          offset: 0,
        }}
      />,
    );

    expect(queryMocks.taskFilters).toEqual({
      channelId: 7,
      status: "failed",
      taskName: "transcript_collect",
      limit: 100,
      offset: 0,
    });
  });

  it("submits filters through the tasks route", () => {
    render(<TasksPage initialFilters={{ limit: 100, offset: 0 }} />);

    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "running" } });
    fireEvent.change(screen.getByLabelText("Task name"), {
      target: { value: "transcript_collect" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Apply/i }));

    expect(routerPush).toHaveBeenCalledWith(
      "/tasks?channelId=7&status=running&taskName=transcript_collect&limit=100",
    );
  });

  it("preserves an unknown selected channel option", () => {
    queryMocks.channels.data = { items: [] };

    render(<TasksPage initialFilters={{ channelId: 99, limit: 100, offset: 0 }} />);

    expect(screen.getByRole("option", { name: "#99" })).toBeTruthy();
  });

  it("disables transcript task retry while transcript collection is running", () => {
    queryMocks.tasks.data = {
      items: [
        {
          videoTaskId: 5,
          videoId: 7,
          youtubeVideoId: "abc123",
          channelId: 7,
          channelName: "Channel",
          taskName: "transcript_collect",
          taskVersion: "v1",
          status: "failed",
          workerId: null,
          timeoutSeconds: 600,
          jobId: 9,
          jobAttemptId: 10,
          outputTranscriptId: null,
          outputJson: null,
          errorType: "TimeoutError",
          errorMessage: "timeout",
          startedAt: "2026-06-18T00:00:00Z",
          completedAt: "2026-06-18T00:10:00Z",
          createdAt: "2026-06-18T00:00:00Z",
          updatedAt: "2026-06-18T00:10:00Z",
        },
      ],
      total: 1,
      limit: 100,
      offset: 0,
    };
    queryMocks.runningTranscriptBatches.data = {
      items: [runningBatch],
      nextCursor: null,
    };

    render(<TasksPage initialFilters={{ limit: 100, offset: 0 }} />);

    const retryButton = screen.getByRole("button", { name: /Retry job/i });
    expect((retryButton as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Transcript collection running")).toBeTruthy();
  });
});
