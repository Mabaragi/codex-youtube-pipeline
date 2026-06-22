import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { JobsPage } from "../jobs-page";
import type {
  OpsChannel,
  OpsVideoTaskList,
  PipelineJobFilters,
  PipelineJobList,
} from "@/lib/types";

const routerPush = vi.hoisted(() => vi.fn());
const queryMocks = vi.hoisted(() => ({
  channels: {
    data: undefined as { items: OpsChannel[] } | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  jobs: {
    data: undefined as PipelineJobList | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  jobFilters: undefined as PipelineJobFilters | undefined,
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
  usePipelineJobs: (filters: PipelineJobFilters) => {
    queryMocks.jobFilters = filters;
    return queryMocks.jobs;
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

describe("JobsPage filters", () => {
  beforeEach(() => {
    routerPush.mockReset();
    queryMocks.channels.data = { items: [channel] };
    queryMocks.jobs.data = {
      items: [
        {
          jobId: 1,
          step: "video_collect",
          status: "failed",
          subjectType: "channel",
          subjectId: 7,
          externalKey: "UC123456789",
          createdAt: "2026-06-18T00:00:00Z",
          updatedAt: "2026-06-18T01:00:00Z",
          completedAt: "2026-06-18T01:00:00Z",
          latestAttemptId: 1,
          latestAttemptStatus: "failed",
          attemptCount: 1,
        },
      ],
      nextCursor: 1,
    };
    queryMocks.jobs.isLoading = false;
    queryMocks.jobs.error = null;
    queryMocks.jobFilters = undefined;
    queryMocks.retryJob.isPending = false;
    queryMocks.retryJob.mutate.mockReset();
    queryMocks.runningTranscriptTasks.data = emptyRunningTasks;
    queryMocks.runningTranscriptTasks.isLoading = false;
    queryMocks.runningTranscriptTasks.isError = false;
    queryMocks.runningTranscriptBatches.data = emptyRunningBatches;
    queryMocks.runningTranscriptBatches.isLoading = false;
    queryMocks.runningTranscriptBatches.isError = false;
  });

  it("passes initial URL filters to the jobs query", () => {
    render(
      <JobsPage
        initialFilters={{
          channelId: 7,
          status: "failed",
          step: "video_collect",
          limit: 50,
        }}
      />,
    );

    expect(queryMocks.jobFilters).toEqual({
      channelId: 7,
      status: "failed",
      step: "video_collect",
      limit: 50,
    });
  });

  it("submits filters through the jobs route", () => {
    render(<JobsPage initialFilters={{ limit: 50 }} />);

    fireEvent.change(screen.getByLabelText("Channel"), { target: { value: "7" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "failed" } });
    fireEvent.change(screen.getByLabelText("Step"), {
      target: { value: "video_collect" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Apply/i }));

    expect(routerPush).toHaveBeenCalledWith(
      "/jobs?channelId=7&status=failed&step=video_collect&limit=50",
    );
  });

  it("keeps filters when linking to older jobs", () => {
    render(
      <JobsPage
        initialFilters={{
          channelId: 7,
          status: "failed",
          step: "video_collect",
          limit: 50,
        }}
      />,
    );

    expect(screen.getByRole("link", { name: /Older/i }).getAttribute("href")).toBe(
      "/jobs?channelId=7&status=failed&step=video_collect&limit=50&cursor=1",
    );
  });

  it("preserves an unknown selected channel option", () => {
    queryMocks.channels.data = { items: [] };

    render(<JobsPage initialFilters={{ channelId: 99, limit: 50 }} />);

    expect(screen.getByRole("option", { name: "#99" })).toBeTruthy();
  });

  it("disables transcript job retry while transcript collection is running", () => {
    queryMocks.jobs.data = {
      items: [
        {
          jobId: 9,
          step: "transcript_collect",
          status: "failed",
          subjectType: "video",
          subjectId: 7,
          externalKey: "abc123",
          createdAt: "2026-06-18T00:00:00Z",
          updatedAt: "2026-06-18T01:00:00Z",
          completedAt: "2026-06-18T01:00:00Z",
          latestAttemptId: 1,
          latestAttemptStatus: "failed",
          attemptCount: 1,
        },
      ],
      nextCursor: null,
    };
    queryMocks.runningTranscriptBatches.data = {
      items: [runningBatch],
      nextCursor: null,
    };

    render(<JobsPage initialFilters={{ limit: 50 }} />);

    const retryButton = screen.getByRole("button", { name: /Retry/i });
    expect((retryButton as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Transcript collection running")).toBeTruthy();
  });
});
