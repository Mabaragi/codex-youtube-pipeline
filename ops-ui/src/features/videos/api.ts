"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/features/query-keys";
import { ApiClientError, requestJson } from "@/lib/api-client";
import type {
  ChannelOperationBatchResult,
  MicroEventExtractionDetail,
  MicroEventOperationRequest,
  OperationBatchResult,
  OpsRefreshVideoEmbedStatusRequest,
  OpsRefreshVideoEmbedStatusResponse,
  OpsVideoDetail,
  OpsVideoFilters,
  OpsVideoList,
  ProcessToPublishOperationRequest,
  TimelineComposition,
  TimelineOperationRequest,
  TranscriptCollectOperationRequest,
  TranscriptContent,
  TranscriptCueList,
  TranscriptCueOperationRequest,
  VideoCollectOperationRequest,
  WorkflowBatchResult,
} from "@/lib/types";

export function useOpsVideos(filters: OpsVideoFilters) {
  return useQuery({
    queryKey: queryKeys.videos(filters),
    queryFn: () => requestJson<OpsVideoList>("/ops/videos", { query: filters }),
  });
}

export function useOpsVideoDetail(videoId: number) {
  return useQuery({
    queryKey: queryKeys.videoDetail(videoId),
    queryFn: () => requestJson<OpsVideoDetail>(`/ops/videos/${videoId}`),
    enabled: Number.isFinite(videoId) && videoId > 0,
  });
}

export function useRefreshVideoEmbedStatusMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: OpsRefreshVideoEmbedStatusRequest = { limit: 200 }) =>
      requestJson<OpsRefreshVideoEmbedStatusResponse>(
        "/ops/operations/embed-status-refresh",
        { method: "POST", body },
      ),
    onSuccess: () => invalidateVideoQueries(queryClient),
  });
}

export function useTranscriptContent(transcriptId: number, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.transcriptContent(transcriptId),
    queryFn: () => fetchTranscriptContent(transcriptId),
    enabled: enabled && Number.isFinite(transcriptId) && transcriptId > 0,
    staleTime: Infinity,
  });
}

export function useTranscriptCues(transcriptId: number, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.transcriptCues(transcriptId),
    queryFn: () =>
      requestJson<TranscriptCueList>(`/ops/transcripts/${transcriptId}/cues`),
    enabled: enabled && Number.isFinite(transcriptId) && transcriptId > 0,
    staleTime: 30_000,
  });
}

export function fetchTranscriptContent(transcriptId: number) {
  return requestJson<TranscriptContent>(`/ops/transcripts/${transcriptId}/content`);
}

export function useMicroEventExtraction(videoId: number, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.microEventExtraction(videoId),
    queryFn: () => fetchLatestMicroEventExtraction(videoId),
    enabled: enabled && Number.isFinite(videoId) && videoId > 0,
    staleTime: 30_000,
  });
}

export function useTimelineComposition(videoId: number, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.timelineComposition(videoId),
    queryFn: () => fetchLatestTimelineComposition(videoId),
    enabled: enabled && Number.isFinite(videoId) && videoId > 0,
    staleTime: 30_000,
  });
}

export async function fetchLatestMicroEventExtraction(
  videoId: number,
): Promise<MicroEventExtractionDetail | null> {
  try {
    return await requestJson<MicroEventExtractionDetail>(
      `/ops/videos/${videoId}/micro-events/latest`,
    );
  } catch (error) {
    if (error instanceof ApiClientError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

export async function fetchLatestTimelineComposition(
  videoId: number,
): Promise<TimelineComposition | null> {
  try {
    return await requestJson<TimelineComposition>(
      `/ops/videos/${videoId}/timelines/latest`,
    );
  } catch (error) {
    if (error instanceof ApiClientError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

export function useCollectVideosOperation() {
  return useOperationMutation<VideoCollectOperationRequest, ChannelOperationBatchResult>(
    "/ops/operations/video-collect",
  );
}

export function useCollectTranscriptsOperation() {
  return useOperationMutation<TranscriptCollectOperationRequest, OperationBatchResult>(
    "/ops/operations/transcript-collect",
  );
}

export function useGenerateTranscriptCuesOperation() {
  return useOperationMutation<TranscriptCueOperationRequest, OperationBatchResult>(
    "/ops/operations/transcript-cue-generate",
  );
}

export function useExtractMicroEventsOperation() {
  return useOperationMutation<MicroEventOperationRequest, OperationBatchResult>(
    "/ops/operations/micro-event-extract",
  );
}

export function useComposeTimelinesOperation() {
  return useOperationMutation<TimelineOperationRequest, OperationBatchResult>(
    "/ops/operations/timeline-compose",
  );
}

export function useProcessToPublishOperation() {
  return useOperationMutation<ProcessToPublishOperationRequest, WorkflowBatchResult>(
    "/ops/workflows/process-to-publish",
  );
}

function useOperationMutation<Request, Response>(path: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Request) =>
      requestJson<Response>(path, { method: "POST", body }),
    onSuccess: () => invalidateVideoQueries(queryClient),
  });
}

function invalidateVideoQueries(queryClient: ReturnType<typeof useQueryClient>) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["ops", "videos"] }),
    queryClient.invalidateQueries({ queryKey: ["ops", "work-items"] }),
    queryClient.invalidateQueries({ queryKey: ["ops", "summary"] }),
  ]);
}
