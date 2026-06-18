import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TasksPage } from "../tasks-page";
import type {
  OpsChannel,
  OpsVideoTaskFilters,
  OpsVideoTaskList,
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
  taskFailedCount: 0,
  taskRunningCount: 0,
  latestVideoPublishedAt: "2026-06-18T00:00:00Z",
  latestTaskUpdatedAt: null,
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
});
