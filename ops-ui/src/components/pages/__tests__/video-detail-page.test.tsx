import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VideoDetailPage } from "../video-detail-page";
import type { OpsVideoDetail, TranscriptContent } from "@/lib/types";

const queryMocks = vi.hoisted(() => {
  const state = {
    content: undefined as TranscriptContent | undefined,
  };
  return {
    contentState: state,
    detail: {
      data: undefined as OpsVideoDetail | undefined,
      isLoading: false,
      error: null as Error | null,
    },
    transcriptContent: vi.fn(
      (_transcriptId: number, enabled: boolean) =>
        ({
          data: enabled ? state.content : undefined,
          isLoading: false,
          error: null,
        }) as {
          data: TranscriptContent | undefined;
          isLoading: boolean;
          error: Error | null;
        },
    ),
  };
});

vi.mock("@/lib/queries", () => ({
  useOpsVideoDetail: () => queryMocks.detail,
  useTranscriptContent: (transcriptId: number, enabled: boolean) =>
    queryMocks.transcriptContent(transcriptId, enabled),
}));

const videoDetail: OpsVideoDetail = {
  videoId: 42,
  channelId: 7,
  channelName: "Channel",
  youtubeVideoId: "abc123DEF45",
  title: "Stored video",
  description: "Stored video description",
  publishedAt: "2026-06-18T00:00:00Z",
  duration: "PT1M",
  thumbnailUrl: null,
  sourceListingApiCallId: 10,
  sourceDetailsApiCallId: 11,
  sourceJobId: 12,
  createdAt: "2026-06-18T00:30:00Z",
  updatedAt: "2026-06-18T00:45:00Z",
  latestTaskId: 9,
  latestTaskName: "transcript_collect",
  latestTaskStatus: "succeeded",
  latestTaskUpdatedAt: "2026-06-18T01:00:00Z",
  transcriptId: 11,
  tasks: [
    {
      videoTaskId: 9,
      videoId: 42,
      channelId: 7,
      channelName: "Channel",
      youtubeVideoId: "abc123DEF45",
      taskName: "transcript_collect",
      taskVersion: "v1",
      status: "succeeded",
      workerId: "manual-api",
      timeoutSeconds: 600,
      jobId: 12,
      jobAttemptId: 13,
      outputTranscriptId: 11,
      errorType: null,
      errorMessage: null,
      startedAt: "2026-06-18T00:50:00Z",
      completedAt: "2026-06-18T00:55:00Z",
      createdAt: "2026-06-18T00:50:00Z",
      updatedAt: "2026-06-18T00:55:00Z",
    },
  ],
  transcripts: [
    {
      id: 11,
      videoId: "abc123DEF45",
      language: "Korean",
      languageCode: "ko",
      isGenerated: true,
      requestedLanguages: ["ko", "en"],
      preserveFormatting: false,
      storage: {
        bucket: "raw",
        objectName: "youtube/transcripts/abc123DEF45-hash.json",
        uri: "s3://raw/youtube/transcripts/abc123DEF45-hash.json",
      },
      responseSha256: "a".repeat(64),
      segmentCount: 2,
      textLength: 23,
      notes: null,
      createdAt: "2026-06-18T00:55:00Z",
      updatedAt: "2026-06-18T00:55:00Z",
    },
  ],
};

const transcriptContent: TranscriptContent = {
  videoId: "abc123DEF45",
  language: "Korean",
  languageCode: "ko",
  isGenerated: true,
  text: "first line\nsecond line",
  segments: [
    { text: "first line", start: 0, duration: 1 },
    { text: "second line", start: 61.25, duration: 2.5 },
  ],
  storage: {
    bucket: "raw",
    objectName: "youtube/transcripts/abc123DEF45-hash.json",
    uri: "s3://raw/youtube/transcripts/abc123DEF45-hash.json",
  },
};

describe("VideoDetailPage", () => {
  beforeEach(() => {
    queryMocks.detail.data = videoDetail;
    queryMocks.detail.isLoading = false;
    queryMocks.detail.error = null;
    queryMocks.contentState.content = transcriptContent;
    queryMocks.transcriptContent.mockClear();
  });

  it("renders video summary, task history, and transcript metadata", () => {
    render(<VideoDetailPage videoId={42} />);

    expect(screen.getByText("Stored video")).toBeTruthy();
    expect(screen.getByText("Stored video description")).toBeTruthy();
    expect(screen.getAllByText("transcript_collect").length).toBeGreaterThan(0);
    expect(screen.getByText("Korean · ko")).toBeTruthy();
  });

  it("loads transcript content only after the transcript is shown", () => {
    render(<VideoDetailPage videoId={42} />);

    expect(screen.queryByText(/first line/)).toBeNull();
    expect(queryMocks.transcriptContent).toHaveBeenLastCalledWith(11, false);

    fireEvent.click(screen.getByRole("button", { name: /Show transcript/i }));

    expect(screen.getByText("Time")).toBeTruthy();
    expect(screen.getByText("Text")).toBeTruthy();
    expect(screen.getByText("00:00-00:01")).toBeTruthy();
    expect(screen.getByText("01:01.25-01:03.75")).toBeTruthy();
    expect(screen.getByText(/first line/)).toBeTruthy();
    expect(screen.getByText(/second line/)).toBeTruthy();
    expect(queryMocks.transcriptContent).toHaveBeenLastCalledWith(11, true);

    fireEvent.click(screen.getByRole("button", { name: /Hide transcript/i }));

    expect(screen.queryByText(/first line/)).toBeNull();
  });

  it("shows a compact empty state when no transcripts are stored", () => {
    queryMocks.detail.data = { ...videoDetail, transcripts: [] };

    render(<VideoDetailPage videoId={42} />);

    expect(screen.getByText("No stored transcripts.")).toBeTruthy();
  });
});
