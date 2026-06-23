import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { VideoDetailPage } from "../video-detail-page";
import type {
  MicroEventExtractResult,
  MicroEventExtractionDetail,
  OpsVideoDetail,
  TranscriptContent,
  TranscriptCueList,
} from "@/lib/types";

const queryMocks = vi.hoisted(() => {
  const state = {
    content: undefined as TranscriptContent | undefined,
    cues: undefined as TranscriptCueList | undefined,
    microEvents: undefined as MicroEventExtractionDetail | null | undefined,
    microEventError: null as Error | null,
  };
  const mutation = {
    data: undefined as MicroEventExtractResult | undefined,
    error: null as Error | null,
    isPending: false,
    mutate: vi.fn(),
  };
  return {
    contentState: state,
    cueState: state,
    microEventState: state,
    detail: {
      data: undefined as OpsVideoDetail | undefined,
      isLoading: false,
      error: null as Error | null,
    },
    extractMicroEventsMutation: vi.fn(() => mutation),
    fetchTranscriptContent: vi.fn(async (transcriptId: number) => {
      void transcriptId;
      return state.content;
    }),
    microEventExtraction: vi.fn(
      (_videoId: number, enabled: boolean) =>
        ({
          data: enabled ? state.microEvents : undefined,
          isLoading: false,
          error: state.microEventError,
        }) as {
          data: MicroEventExtractionDetail | null | undefined;
          isLoading: boolean;
          error: Error | null;
        },
    ),
    mutation,
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
    transcriptCues: vi.fn(
      (_transcriptId: number, enabled: boolean) =>
        ({
          data: enabled ? state.cues : undefined,
          isLoading: false,
          error: null,
        }) as {
          data: TranscriptCueList | undefined;
          isLoading: boolean;
          error: Error | null;
        },
    ),
  };
});

vi.mock("@/lib/queries", () => ({
  useExtractMicroEventsMutation: () => queryMocks.extractMicroEventsMutation(),
  useMicroEventExtraction: (videoId: number, enabled: boolean) =>
    queryMocks.microEventExtraction(videoId, enabled),
  fetchTranscriptContent: (transcriptId: number) =>
    queryMocks.fetchTranscriptContent(transcriptId),
  useOpsVideoDetail: () => queryMocks.detail,
  useTranscriptContent: (transcriptId: number, enabled: boolean) =>
    queryMocks.transcriptContent(transcriptId, enabled),
  useTranscriptCues: (transcriptId: number, enabled: boolean) =>
    queryMocks.transcriptCues(transcriptId, enabled),
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
      videoTaskId: 10,
      videoId: 42,
      channelId: 7,
      channelName: "Channel",
      youtubeVideoId: "abc123DEF45",
      taskName: "transcript_cue_generate",
      taskVersion: "v1",
      status: "succeeded",
      workerId: "manual-api",
      timeoutSeconds: 600,
      jobId: 14,
      jobAttemptId: 15,
      outputTranscriptId: 11,
      outputJson: { cueCount: 2 },
      errorType: null,
      errorMessage: null,
      startedAt: "2026-06-18T00:56:00Z",
      completedAt: "2026-06-18T00:57:00Z",
      createdAt: "2026-06-18T00:56:00Z",
      updatedAt: "2026-06-18T00:57:00Z",
    },
    {
      videoTaskId: 16,
      videoId: 42,
      channelId: 7,
      channelName: "Channel",
      youtubeVideoId: "abc123DEF45",
      taskName: "micro_event_extract",
      taskVersion: "v1",
      status: "succeeded",
      workerId: "manual-api",
      timeoutSeconds: 3600,
      jobId: 16,
      jobAttemptId: 17,
      outputTranscriptId: 11,
      outputJson: {
        windowCount: 1,
        microEventCount: 1,
        excludedRangeCount: 1,
        asrCorrectionCandidateCount: 1,
      },
      errorType: null,
      errorMessage: null,
      startedAt: "2026-06-18T00:58:00Z",
      completedAt: "2026-06-18T00:59:00Z",
      createdAt: "2026-06-18T00:58:00Z",
      updatedAt: "2026-06-18T00:59:00Z",
    },
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
      outputJson: null,
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

const transcriptCues: TranscriptCueList = {
  transcriptId: 11,
  cueCount: 2,
  items: [
    {
      id: 101,
      transcriptId: 11,
      cueId: "tr11-c000001",
      cueIndex: 1,
      sourceSegmentIndex: 0,
      startMs: 0,
      endMs: 1000,
      durationMs: 1000,
      text: "first line",
      sourceJobId: 14,
      sourceJobAttemptId: 15,
      createdAt: "2026-06-18T00:57:00Z",
      updatedAt: "2026-06-18T00:57:00Z",
    },
    {
      id: 102,
      transcriptId: 11,
      cueId: "tr11-c000002",
      cueIndex: 2,
      sourceSegmentIndex: 1,
      startMs: 61_250,
      endMs: 63_750,
      durationMs: 2500,
      text: "second line",
      sourceJobId: 14,
      sourceJobAttemptId: 15,
      createdAt: "2026-06-18T00:57:00Z",
      updatedAt: "2026-06-18T00:57:00Z",
    },
  ],
};

const microEventExtraction: MicroEventExtractionDetail = {
  videoTaskId: 16,
  videoId: 42,
  youtubeVideoId: "abc123DEF45",
  transcriptId: 11,
  status: "succeeded",
  jobId: 16,
  jobAttemptId: 17,
  windowCount: 1,
  microEventCount: 1,
  asrCorrectionCandidateCount: 1,
  firstCueId: "tr11-c000001",
  lastCueId: "tr11-c000002",
  outputJson: {
    windowCount: 1,
    microEventCount: 1,
    excludedRangeCount: 1,
    asrCorrectionCandidateCount: 1,
  },
  errorType: null,
  errorMessage: null,
  startedAt: "2026-06-18T00:58:00Z",
  completedAt: "2026-06-18T00:59:00Z",
  createdAt: "2026-06-18T00:58:00Z",
  updatedAt: "2026-06-18T00:59:00Z",
  windows: [
    {
      windowId: 201,
      windowIndex: 1,
      startCueId: "tr11-c000001",
      endCueId: "tr11-c000002",
      cueCount: 2,
      status: "succeeded",
      carryOutUnfinished: false,
      codexThreadId: "thread-1",
      codexTurnId: "turn-1",
      rawResponseText: '{"micro_events":[]}',
      parsedResponseJson: { micro_events: [] },
      validationError: null,
      sourceJobId: 16,
      sourceJobAttemptId: 17,
      createdAt: "2026-06-18T00:59:00Z",
      updatedAt: "2026-06-18T00:59:00Z",
      microEvents: [
        {
          microEventCandidateId: 301,
          candidateIndex: 1,
          activity: "JUST_CHATTING",
          event: "Streamer reacts to the opening chat topic.",
          startCueId: "tr11-c000001",
          endCueId: "tr11-c000002",
          evidenceCueIds: ["tr11-c000001"],
          boundaryBefore: true,
          boundaryAfter: false,
          confidence: 0.87,
          programMode: "JUST_CHATTING",
          contentKind: "META_CHAT",
          topics: ["opening chat"],
          relationToPrevious: "NEW_TOPIC",
          continuesToNext: false,
          supportLevel: "DIRECT",
          createdAt: "2026-06-18T00:59:00Z",
          updatedAt: "2026-06-18T00:59:00Z",
        },
      ],
      excludedRanges: [
        {
          excludedRangeId: 501,
          rangeIndex: 1,
          startCueId: "tr11-c000002",
          endCueId: "tr11-c000002",
          reason: "LOW_INFORMATION",
          createdAt: "2026-06-18T00:59:00Z",
          updatedAt: "2026-06-18T00:59:00Z",
        },
      ],
      asrCorrectionCandidates: [
        {
          asrCorrectionCandidateId: 401,
          candidateIndex: 1,
          original: "recoding",
          suggested: "recording",
          correctionType: "COMMON_WORD",
          applyScope: "SEARCH_ONLY",
          evidenceCueIds: ["tr11-c000002"],
          confidence: 0.8,
          createdAt: "2026-06-18T00:59:00Z",
          updatedAt: "2026-06-18T00:59:00Z",
        },
      ],
    },
  ],
};

let downloadedBlob: Blob | null = null;
let downloadedFileName = "";
let anchorClick: ReturnType<typeof vi.fn>;

describe("VideoDetailPage", () => {
  beforeAll(() => {
    anchorClick = vi.fn();
    URL.createObjectURL = vi.fn((blob: Blob | MediaSource) => {
      downloadedBlob = blob as Blob;
      return "blob:transcript";
    });
    URL.revokeObjectURL = vi.fn();

    const originalCreateElement = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation((tagName) => {
      const element = originalCreateElement(tagName);
      if (tagName.toLowerCase() === "a") {
        Object.defineProperty(element, "click", { value: anchorClick });
        Object.defineProperty(element, "download", {
          get: () => downloadedFileName,
          set: (value: string) => {
            downloadedFileName = value;
          },
        });
      }
      return element;
    });
  });

  beforeEach(() => {
    queryMocks.detail.data = videoDetail;
    queryMocks.detail.isLoading = false;
    queryMocks.detail.error = null;
    queryMocks.contentState.content = transcriptContent;
    queryMocks.cueState.cues = transcriptCues;
    queryMocks.microEventState.microEvents = microEventExtraction;
    queryMocks.microEventState.microEventError = null;
    queryMocks.mutation.data = undefined;
    queryMocks.mutation.error = null;
    queryMocks.mutation.isPending = false;
    queryMocks.mutation.mutate.mockClear();
    queryMocks.extractMicroEventsMutation.mockClear();
    queryMocks.fetchTranscriptContent.mockClear();
    queryMocks.microEventExtraction.mockClear();
    queryMocks.transcriptContent.mockClear();
    queryMocks.transcriptCues.mockClear();
    downloadedBlob = null;
    downloadedFileName = "";
    anchorClick.mockClear();
  });

  it("renders video summary, task history, and transcript metadata", () => {
    render(<VideoDetailPage videoId={42} />);

    expect(screen.getByText("Stored video")).toBeTruthy();
    expect(screen.getByText("Stored video description")).toBeTruthy();
    expect(screen.getAllByText("transcript_collect").length).toBeGreaterThan(0);
    expect(screen.getAllByText("transcript_cue_generate").length).toBeGreaterThan(0);
    expect(screen.getAllByText("micro_event_extract").length).toBeGreaterThan(0);
    expect(screen.getAllByText("#10").length).toBeGreaterThan(0);
    expect(screen.getByText("2")).toBeTruthy();
    expect(screen.getByText("Korean · ko")).toBeTruthy();
  });

  it("renders latest micro-event extraction candidates", () => {
    render(<VideoDetailPage videoId={42} />);

    expect(screen.getByText("Micro Events")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Download JSON/i })).toBeTruthy();
    expect(screen.getByText("Window #1")).toBeTruthy();
    expect(screen.getByText("Streamer reacts to the opening chat topic.")).toBeTruthy();
    expect(screen.getByText("META_CHAT")).toBeTruthy();
    expect(screen.getByText("opening chat")).toBeTruthy();
    expect(screen.getByText("Excluded Ranges")).toBeTruthy();
    expect(screen.getByText("LOW_INFORMATION")).toBeTruthy();
    expect(screen.getByText("recoding -> recording")).toBeTruthy();
    expect(screen.getByText("ASR Candidates")).toBeTruthy();
    expect(queryMocks.microEventExtraction).toHaveBeenLastCalledWith(42, true);
  });

  it("runs micro-event extraction from the detail panel", () => {
    render(<VideoDetailPage videoId={42} />);

    fireEvent.click(screen.getByRole("button", { name: /Regenerate/i }));

    expect(queryMocks.mutation.mutate).toHaveBeenCalledWith({
      videoId: 42,
      retryFailed: false,
      regenerateSucceeded: true,
    });
  });

  it("shows an empty micro-event state before extraction", () => {
    queryMocks.microEventState.microEvents = null;
    queryMocks.detail.data = {
      ...videoDetail,
      tasks: videoDetail.tasks.filter((task) => task.taskName !== "micro_event_extract"),
    };

    render(<VideoDetailPage videoId={42} />);

    expect(screen.getByText("No extraction yet.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Download JSON/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Extract events/i }));
    expect(queryMocks.mutation.mutate).toHaveBeenCalledWith({
      videoId: 42,
      retryFailed: false,
      regenerateSucceeded: false,
    });
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

  it("loads transcript cues only after cues are shown", () => {
    render(<VideoDetailPage videoId={42} />);

    expect(screen.queryByText("tr11-c000001")).toBeNull();
    expect(queryMocks.transcriptCues).toHaveBeenLastCalledWith(11, false);

    fireEvent.click(screen.getByRole("button", { name: /Show cues/i }));

    expect(screen.getByText("Cue")).toBeTruthy();
    expect(screen.getByText("tr11-c000001")).toBeTruthy();
    expect(screen.getByText("00:00-00:01")).toBeTruthy();
    expect(screen.getByText("seg #0")).toBeTruthy();
    expect(screen.getAllByText("2 cues").length).toBeGreaterThan(0);
    expect(queryMocks.transcriptCues).toHaveBeenLastCalledWith(11, true);

    fireEvent.click(screen.getByRole("button", { name: /Hide cues/i }));

    expect(screen.queryByText("tr11-c000001")).toBeNull();
  });

  it("downloads transcript content as SRT before the transcript is shown", async () => {
    render(<VideoDetailPage videoId={42} />);

    fireEvent.click(screen.getByRole("button", { name: /SRT/i }));

    await waitFor(() => expect(queryMocks.fetchTranscriptContent).toHaveBeenCalledWith(11));
    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(downloadedFileName).toBe("abc123DEF45-ko-11.srt");
    expect(downloadedBlob?.type).toBe("application/x-subrip;charset=utf-8");
    await expect(downloadedBlob?.text()).resolves.toContain(
      "1\r\n00:00:00,000 --> 00:00:01,000\r\nfirst line",
    );
  });

  it("downloads loaded transcript content as TXT and JSON without refetching", async () => {
    render(<VideoDetailPage videoId={42} />);
    fireEvent.click(screen.getByRole("button", { name: /Show transcript/i }));

    fireEvent.click(screen.getByRole("button", { name: /TXT/i }));

    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(queryMocks.fetchTranscriptContent).not.toHaveBeenCalled();
    expect(downloadedFileName).toBe("abc123DEF45-ko-11.txt");
    expect(downloadedBlob?.type).toBe("text/plain;charset=utf-8");
    await expect(downloadedBlob?.text()).resolves.toBe("first line\nsecond line");

    fireEvent.click(screen.getByRole("button", { name: /^JSON$/i }));

    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(2));
    expect(downloadedFileName).toBe("abc123DEF45-ko-11.json");
    expect(downloadedBlob?.type).toBe("application/json;charset=utf-8");
    await expect(downloadedBlob?.text()).resolves.toContain('"videoId": "abc123DEF45"');
  });

  it("downloads the latest micro-event extraction as one JSON file", async () => {
    render(<VideoDetailPage videoId={42} />);

    fireEvent.click(screen.getByRole("button", { name: /Download JSON/i }));

    await waitFor(() => expect(anchorClick).toHaveBeenCalledTimes(1));
    expect(downloadedFileName).toBe("abc123DEF45-micro-events-task-16.json");
    expect(downloadedBlob?.type).toBe("application/json;charset=utf-8");
    const payload = JSON.parse((await downloadedBlob?.text()) ?? "{}") as Record<
      string,
      unknown
    >;
    expect(payload.videoTaskId).toBe(16);
    expect(payload.windows).toEqual(microEventExtraction.windows);
    expect(JSON.stringify(payload)).toContain("Streamer reacts to the opening chat topic.");
    expect(JSON.stringify(payload)).toContain("recoding");
    expect(JSON.stringify(payload)).toContain("LOW_INFORMATION");
    expect(JSON.stringify(payload)).toContain("rawResponseText");
  });

  it("shows a compact empty state when no transcripts are stored", () => {
    queryMocks.detail.data = { ...videoDetail, transcripts: [] };

    render(<VideoDetailPage videoId={42} />);

    expect(screen.getByText("No stored transcripts.")).toBeTruthy();
  });
});
