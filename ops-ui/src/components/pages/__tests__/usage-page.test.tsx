import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { UsagePage } from "../usage-page";
import type {
  CodexUsageByJobFilters,
  CodexUsageByJobList,
  CodexUsageByVideoFilters,
  CodexUsageByVideoList,
  CodexUsageFilters,
  CodexUsageList,
} from "@/lib/types";

const routerPush = vi.hoisted(() => vi.fn());
const queryMocks = vi.hoisted(() => ({
  usage: {
    data: undefined as CodexUsageList | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  usageByVideo: {
    data: undefined as CodexUsageByVideoList | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  usageByJob: {
    data: undefined as CodexUsageByJobList | undefined,
    isLoading: false,
    error: null as Error | null,
  },
  filters: undefined as CodexUsageFilters | undefined,
  byVideoFilters: undefined as CodexUsageByVideoFilters | undefined,
  byJobFilters: undefined as CodexUsageByJobFilters | undefined,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("@/lib/queries", () => ({
  useCodexUsage: (filters: CodexUsageFilters) => {
    queryMocks.filters = filters;
    return queryMocks.usage;
  },
  useCodexUsageByVideo: (filters: CodexUsageByVideoFilters) => {
    queryMocks.byVideoFilters = filters;
    return queryMocks.usageByVideo;
  },
  useCodexUsageByJob: (filters: CodexUsageByJobFilters) => {
    queryMocks.byJobFilters = filters;
    return queryMocks.usageByJob;
  },
}));

const usageList: CodexUsageList = {
  items: [
    {
      codexUsageId: 12,
      source: "micro_event_extract",
      operation: "extract_window",
      model: "gpt-5.4",
      reasoningEffort: "high",
      status: "succeeded",
      threadId: "thread-123456789",
      turnId: "turn-123456789",
      usageJson: { totalTokens: 33 },
      inputTokens: 20,
      outputTokens: 13,
      totalTokens: 33,
      cachedInputTokens: 2,
      reasoningOutputTokens: 1,
      durationMs: 1234,
      errorType: null,
      errorMessage: null,
      videoId: 1,
      videoTaskId: 2,
      jobId: 3,
      jobAttemptId: 4,
      transcriptId: 5,
      windowIndex: 6,
      createdAt: "2026-06-23T05:18:00Z",
    },
  ],
  nextCursor: 9,
  summary: {
    runCount: 2,
    inputTokens: 40,
    outputTokens: 26,
    totalTokens: 66,
    cachedInputTokens: 4,
    reasoningOutputTokens: 2,
  },
};

const usageByVideoList: CodexUsageByVideoList = {
  items: [
    {
      videoId: 1,
      youtubeVideoId: "youtube-1",
      title: "Video 1",
      runCount: 2,
      inputTokens: 40,
      outputTokens: 26,
      totalTokens: 66,
      cachedInputTokens: 4,
      reasoningOutputTokens: 2,
      latestModel: "gpt-5.4",
      latestReasoningEffort: "high",
      latestCreatedAt: "2026-06-23T05:18:00Z",
    },
  ],
  summary: {
    runCount: 2,
    inputTokens: 40,
    outputTokens: 26,
    totalTokens: 66,
    cachedInputTokens: 4,
    reasoningOutputTokens: 2,
  },
};

const usageByJobList: CodexUsageByJobList = {
  items: [
    {
      jobId: 3,
      jobStep: "micro_event_extract",
      jobStatus: "succeeded",
      subjectType: "video",
      subjectId: 1,
      externalKey: "youtube-1",
      runCount: 1,
      inputTokens: 20,
      outputTokens: 13,
      totalTokens: 33,
      cachedInputTokens: 2,
      reasoningOutputTokens: 1,
      latestModel: "gpt-5.4",
      latestReasoningEffort: "high",
      latestCreatedAt: "2026-06-23T05:18:00Z",
    },
    {
      jobId: null,
      jobStep: null,
      jobStatus: null,
      subjectType: null,
      subjectId: null,
      externalKey: null,
      runCount: 1,
      inputTokens: 20,
      outputTokens: 13,
      totalTokens: 33,
      cachedInputTokens: 2,
      reasoningOutputTokens: 1,
      latestModel: "gpt-5.4",
      latestReasoningEffort: "high",
      latestCreatedAt: "2026-06-23T05:18:00Z",
    },
  ],
  summary: {
    runCount: 2,
    inputTokens: 40,
    outputTokens: 26,
    totalTokens: 66,
    cachedInputTokens: 4,
    reasoningOutputTokens: 2,
  },
};

describe("UsagePage", () => {
  beforeEach(() => {
    routerPush.mockReset();
    queryMocks.usage.data = usageList;
    queryMocks.usage.isLoading = false;
    queryMocks.usage.error = null;
    queryMocks.usageByVideo.data = usageByVideoList;
    queryMocks.usageByVideo.isLoading = false;
    queryMocks.usageByVideo.error = null;
    queryMocks.usageByJob.data = usageByJobList;
    queryMocks.usageByJob.isLoading = false;
    queryMocks.usageByJob.error = null;
    queryMocks.byJobFilters = undefined;
  });

  it("renders codex usage summary and rows", () => {
    render(<UsagePage initialFilters={{ limit: 50 }} />);

    expect(screen.getByText("Codex Usage")).toBeTruthy();
    expect(screen.getByText("66")).toBeTruthy();
    expect(screen.getAllByText("micro_event_extract").length).toBeGreaterThan(0);
    expect(screen.getByText("extract_window")).toBeTruthy();
    expect(screen.getAllByText("gpt-5.4").length).toBeGreaterThan(0);
    expect(screen.getAllByText("high").length).toBeGreaterThan(0);
    expect(screen.getByText("By Video")).toBeTruthy();
    expect(screen.getByText("Video 1")).toBeTruthy();
    expect(screen.getByText("33 total")).toBeTruthy();
    expect(screen.getAllByText("video #1").length).toBeGreaterThan(0);
    expect(screen.getByText("window #6")).toBeTruthy();
    expect(screen.getByText("Older")).toBeTruthy();
    expect(queryMocks.filters).toEqual({ limit: 50 });
    expect(queryMocks.byVideoFilters).toEqual({ limit: 50 });
  });

  it("expands a video to show job usage summaries", () => {
    render(
      <UsagePage
        initialFilters={{
          source: "micro_event_extract",
          model: "gpt-5.4",
          limit: 50,
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Show jobs for video 1" }));

    expect(screen.getByText("By Job")).toBeTruthy();
    expect(screen.getByText("#3 micro_event_extract")).toBeTruthy();
    expect(screen.getAllByText("Unlinked").length).toBeGreaterThan(0);
    expect(screen.getAllByText("View runs")[0].closest("a")?.getAttribute("href")).toBe(
      "/usage?source=micro_event_extract&model=gpt-5.4&limit=50&videoId=1&jobId=3",
    );
    expect(queryMocks.byJobFilters).toEqual({
      source: "micro_event_extract",
      model: "gpt-5.4",
      videoId: 1,
      limit: 50,
    });
  });

  it("renders row tokens from nested usage json when token columns are null", () => {
    queryMocks.usage.data = {
      ...usageList,
      items: [
        {
          ...usageList.items[0],
          usageJson: {
            total: {
              inputTokens: 20,
              outputTokens: 13,
              totalTokens: 33,
              cachedInputTokens: 2,
              reasoningOutputTokens: 1,
            },
          },
          inputTokens: null,
          outputTokens: null,
          totalTokens: null,
          cachedInputTokens: null,
          reasoningOutputTokens: null,
        },
      ],
    };

    render(<UsagePage initialFilters={{ limit: 50 }} />);

    expect(screen.getByText("33 total")).toBeTruthy();
    expect(screen.getByText("in 20 / out 13")).toBeTruthy();
    expect(screen.getByText("cached 2 / reasoning 1")).toBeTruthy();
  });

  it("applies filters through the URL", () => {
    render(<UsagePage initialFilters={{ limit: 50 }} />);

    fireEvent.change(screen.getByLabelText("Source"), {
      target: { value: "micro_event_extract" },
    });
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "succeeded" },
    });
    fireEvent.change(screen.getByLabelText("Model"), {
      target: { value: "gpt-5.4" },
    });
    fireEvent.change(screen.getByLabelText("Reasoning"), {
      target: { value: "high" },
    });
    fireEvent.change(screen.getByLabelText("Task ID"), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Apply/i }));

    expect(routerPush).toHaveBeenCalledWith(
      "/usage?source=micro_event_extract&status=succeeded&model=gpt-5.4&reasoningEffort=high&videoTaskId=2&limit=50",
    );
  });

  it("renders empty usage state", () => {
    queryMocks.usage.data = {
      ...usageList,
      items: [],
      nextCursor: null,
      summary: {
        runCount: 0,
        inputTokens: 0,
        outputTokens: 0,
        totalTokens: 0,
        cachedInputTokens: 0,
        reasoningOutputTokens: 0,
      },
    };
    queryMocks.usageByVideo.data = {
      ...usageByVideoList,
      items: [],
      summary: {
        runCount: 0,
        inputTokens: 0,
        outputTokens: 0,
        totalTokens: 0,
        cachedInputTokens: 0,
        reasoningOutputTokens: 0,
      },
    };
    queryMocks.usageByJob.data = {
      ...usageByJobList,
      items: [],
      summary: {
        runCount: 0,
        inputTokens: 0,
        outputTokens: 0,
        totalTokens: 0,
        cachedInputTokens: 0,
        reasoningOutputTokens: 0,
      },
    };

    render(<UsagePage initialFilters={{ limit: 50 }} />);

    expect(screen.getAllByText("No rows.").length).toBeGreaterThan(0);
  });
});
