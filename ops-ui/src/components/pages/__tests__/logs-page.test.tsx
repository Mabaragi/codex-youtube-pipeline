import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LogsPage } from "../logs-page";
import type { OperationEvent, OperationEventList } from "@/lib/types";

const routerPush = vi.hoisted(() => vi.fn());
const queryMocks = vi.hoisted(() => ({
  events: {
    data: undefined as OperationEventList | undefined,
    isLoading: false,
    error: null as Error | null,
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("@/lib/queries", () => ({
  useOperationEvents: () => queryMocks.events,
}));

const event: OperationEvent = {
  eventId: 1,
  occurredAt: "2026-06-19T00:00:00Z",
  eventType: "video_collect.failed",
  severity: "error",
  message: "Channel video collection failed.",
  actorType: "manual_api",
  source: "videos.collect",
  jobId: 10,
  jobAttemptId: 11,
  videoTaskId: null,
  workItemId: 20,
  workAttemptId: 21,
  workBatchId: 22,
  channelId: 2,
  videoId: null,
  externalApiCallId: null,
  subjectType: "channel",
  subjectId: 2,
  externalKey: "UC123456789",
  correlationId: null,
  errorType: "UpstreamError",
  errorMessage: "failed",
  metadata: { attemptId: 11 },
};

describe("LogsPage", () => {
  beforeEach(() => {
    routerPush.mockReset();
    queryMocks.events.data = { items: [event], nextCursor: null };
    queryMocks.events.isLoading = false;
    queryMocks.events.error = null;
  });

  it("renders events and selected metadata", () => {
    render(<LogsPage initialFilters={{ limit: 50 }} />);

    expect(screen.getAllByText("video_collect.failed")).toHaveLength(2);
    expect(screen.getByText("Channel video collection failed.")).toBeTruthy();
    expect(screen.getByText("UpstreamError")).toBeTruthy();
    expect(screen.getByText(/"attemptId": 11/)).toBeTruthy();
  });

  it("submits filters through the logs route", () => {
    render(<LogsPage initialFilters={{ limit: 50 }} />);

    fireEvent.change(screen.getByLabelText("Severity"), { target: { value: "error" } });
    fireEvent.change(screen.getByLabelText("Work item ID"), { target: { value: "20" } });
    fireEvent.click(screen.getByRole("button", { name: /Apply/i }));

    expect(routerPush).toHaveBeenCalledWith(
      "/logs?severity=error&workItemId=20&limit=50",
    );
  });
});
