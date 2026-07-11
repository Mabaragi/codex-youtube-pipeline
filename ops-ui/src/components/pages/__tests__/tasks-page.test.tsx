import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkItemFilters, WorkItemList } from "@/lib/types";
import { TasksPage } from "../tasks-page";

const routerPush = vi.hoisted(() => vi.fn());
const mocks = vi.hoisted(() => ({
  filters: undefined as WorkItemFilters | undefined,
  query: { data: undefined as WorkItemList | undefined, isLoading: false, error: null as Error | null },
  retry: { isPending: false, mutate: vi.fn() },
  cancel: { isPending: false, mutate: vi.fn() },
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: routerPush }) }));
vi.mock("@/features/work/api", () => ({
  useWorkItems: (filters: WorkItemFilters) => {
    mocks.filters = filters;
    return mocks.query;
  },
  useRetryWorkItemMutation: () => mocks.retry,
  useCancelWorkItemMutation: () => mocks.cancel,
}));

const failedWork = {
  id: 41,
  taskType: "transcript_collect",
  subjectType: "video",
  subjectId: 7,
  externalKey: "yt-7",
  taskVersion: "v1",
  inputHash: "hash",
  executionMode: "queued",
  status: "failed",
  outcomeCode: null,
  priority: 0,
  timeoutSeconds: 600,
  input: {},
  output: null,
  outputTranscriptId: null,
  errorCode: "upstream_error",
  errorType: "UpstreamError",
  errorMessage: "failed",
  leaseOwner: null,
  leaseExpiresAt: null,
  availableAt: "2026-07-01T00:00:00Z",
  startedAt: "2026-07-01T00:00:00Z",
  completedAt: "2026-07-01T00:01:00Z",
  createdAt: "2026-07-01T00:00:00Z",
  updatedAt: "2026-07-01T00:01:00Z",
} as const;

describe("TasksPage", () => {
  beforeEach(() => {
    routerPush.mockReset();
    mocks.retry.mutate.mockReset();
    mocks.cancel.mutate.mockReset();
    mocks.query.data = { items: [failedWork], nextCursor: 40 };
    mocks.query.error = null;
  });

  it("queries and renders unified work items", () => {
    const filters: WorkItemFilters = { taskType: "transcript_collect", status: "failed", limit: 50 };
    render(<TasksPage initialFilters={filters} />);
    expect(mocks.filters).toEqual(filters);
    expect(screen.getByText("#41 transcript_collect")).toBeTruthy();
    expect(screen.getByText(/UpstreamError/)).toBeTruthy();
  });

  it("submits work filters and keeps cursor pagination", () => {
    render(<TasksPage initialFilters={{ limit: 50 }} />);
    fireEvent.change(screen.getByLabelText("State"), { target: { value: "running" } });
    fireEvent.change(screen.getByLabelText("Work type"), { target: { value: "micro_event_extract" } });
    fireEvent.change(screen.getByLabelText("Subject type"), { target: { value: "video" } });
    fireEvent.click(screen.getByRole("button", { name: /Apply/i }));
    expect(routerPush).toHaveBeenCalledWith("/tasks?status=running&taskType=micro_event_extract&subjectType=video&limit=50");
    expect(screen.getByRole("link", { name: "Older" }).getAttribute("href")).toBe("/tasks?limit=50&cursor=40");
  });

  it("retries failed work by work item id", () => {
    render(<TasksPage initialFilters={{ limit: 50 }} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(mocks.retry.mutate).toHaveBeenCalledWith({ workItemId: 41 });
  });
});
