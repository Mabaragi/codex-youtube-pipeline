"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiClientError, requestJson } from "@/lib/api-client";
import type {
  CollectAllTranscriptsResult,
  CollectChannelTranscriptsResult,
  CollectChannelVideosResult,
  GenerateAllTranscriptCuesResult,
  GenerateChannelTranscriptCuesResult,
  MicroEventExtractRequest,
  MicroEventExtractResult,
  MicroEventExtractionDetail,
  CodexUsageFilters,
  CodexUsageByVideoFilters,
  CodexUsageByVideoList,
  CodexUsageList,
  OperationEventFilters,
  OperationEventList,
  OpsChannelList,
  OpsSchemaGraph,
  OpsSummary,
  OpsVideoDetail,
  OpsVideoFilters,
  OpsVideoList,
  OpsVideoTaskFilters,
  OpsVideoTaskList,
  PipelineJobFilters,
  PipelineJobList,
  ResolveYouTubeChannelResult,
  RetryPipelineJobResult,
  Streamer,
  TranscriptContent,
  TranscriptCueList,
} from "@/lib/types";

export const queryKeys = {
  summary: ["ops", "summary"] as const,
  channels: ["ops", "channels"] as const,
  videos: (filters: Record<string, unknown>) => ["ops", "videos", filters] as const,
  videoDetail: (videoId: number) => ["ops", "videos", videoId] as const,
  tasks: (filters: Record<string, unknown>) => ["ops", "tasks", filters] as const,
  events: (filters: Record<string, unknown>) => ["ops", "events", filters] as const,
  streamers: ["streamers"] as const,
  jobs: (filters: Record<string, unknown>) => ["pipeline", "jobs", filters] as const,
  codexUsage: (filters: Record<string, unknown>) =>
    ["ops", "codex-usage", filters] as const,
  codexUsageByVideo: (filters: Record<string, unknown>) =>
    ["ops", "codex-usage", "by-video", filters] as const,
  schemaGraph: ["ops", "schema-graph"] as const,
  transcriptContent: (transcriptId: number) =>
    ["youtube-transcripts", transcriptId, "content"] as const,
  transcriptCues: (transcriptId: number) =>
    ["youtube-transcripts", transcriptId, "cues"] as const,
  microEventExtraction: (videoId: number) =>
    ["micro-event-extractions", videoId, "latest"] as const,
};

export function useOpsSummary() {
  return useQuery({
    queryKey: queryKeys.summary,
    queryFn: () => requestJson<OpsSummary>("/ops/summary"),
    refetchInterval: 10_000,
  });
}

export function useOpsChannels() {
  return useQuery({
    queryKey: queryKeys.channels,
    queryFn: () => requestJson<OpsChannelList>("/ops/channels"),
    refetchInterval: 10_000,
  });
}

export function useStreamers() {
  return useQuery({
    queryKey: queryKeys.streamers,
    queryFn: () => requestJson<Streamer[]>("/streamers"),
  });
}

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
      requestJson<TranscriptCueList>(`/youtube-transcripts/${transcriptId}/cues`),
    enabled: enabled && Number.isFinite(transcriptId) && transcriptId > 0,
    staleTime: 30_000,
  });
}

export function fetchTranscriptContent(transcriptId: number) {
  return requestJson<TranscriptContent>(`/youtube-transcripts/${transcriptId}/content`);
}

export function useMicroEventExtraction(videoId: number, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.microEventExtraction(videoId),
    queryFn: () => fetchLatestMicroEventExtraction(videoId),
    enabled: enabled && Number.isFinite(videoId) && videoId > 0,
    staleTime: 30_000,
  });
}

export async function fetchLatestMicroEventExtraction(
  videoId: number,
): Promise<MicroEventExtractionDetail | null> {
  try {
    return await requestJson<MicroEventExtractionDetail>(
      `/videos/${videoId}/micro-event-extractions/latest`,
    );
  } catch (error) {
    if (error instanceof ApiClientError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

export function useOpsVideoTasks(filters: OpsVideoTaskFilters) {
  return useQuery({
    queryKey: queryKeys.tasks(filters),
    queryFn: () =>
      requestJson<OpsVideoTaskList>("/ops/video-tasks", { query: filters }),
    refetchInterval: 5_000,
  });
}

export function useOperationEvents(filters: OperationEventFilters) {
  return useQuery({
    queryKey: queryKeys.events(filters),
    queryFn: () => requestJson<OperationEventList>("/ops/events", { query: filters }),
    refetchInterval: 5_000,
  });
}

export function useCodexUsage(filters: CodexUsageFilters) {
  return useQuery({
    queryKey: queryKeys.codexUsage(filters),
    queryFn: () => requestJson<CodexUsageList>("/ops/codex-usage", { query: filters }),
    refetchInterval: 10_000,
  });
}

export function useCodexUsageByVideo(filters: CodexUsageByVideoFilters) {
  return useQuery({
    queryKey: queryKeys.codexUsageByVideo(filters),
    queryFn: () =>
      requestJson<CodexUsageByVideoList>("/ops/codex-usage/by-video", {
        query: filters,
      }),
    refetchInterval: 10_000,
  });
}

export function useRunningTranscriptTasks() {
  const filters = {
    taskName: "transcript_collect",
    status: "running",
    limit: 1,
    offset: 0,
  } satisfies OpsVideoTaskFilters;
  return useQuery({
    queryKey: queryKeys.tasks(filters),
    queryFn: () =>
      requestJson<OpsVideoTaskList>("/ops/video-tasks", { query: filters }),
    refetchInterval: 2_000,
  });
}

export function useRunningTranscriptBatches() {
  const filters = {
    step: "transcript_collect_batch",
    status: "running",
    limit: 1,
  } satisfies PipelineJobFilters;
  return useQuery({
    queryKey: queryKeys.jobs(filters),
    queryFn: () =>
      requestJson<PipelineJobList>("/pipeline/jobs", {
        query: {
          status: filters.status,
          step: filters.step,
          limit: filters.limit,
        },
      }),
    refetchInterval: 2_000,
  });
}

export function usePipelineJobs(filters: PipelineJobFilters = {}) {
  return useQuery({
    queryKey: queryKeys.jobs(filters),
    queryFn: () =>
      requestJson<PipelineJobList>("/pipeline/jobs", {
        query: {
          channelId: filters.channelId,
          status: filters.status,
          step: filters.step,
          subjectType: filters.subjectType,
          subjectId: filters.subjectId,
          externalKey: filters.externalKey,
          cursor: filters.cursor,
          limit: filters.limit ?? 50,
        },
      }),
    refetchInterval: 5_000,
  });
}

export function useSchemaGraph() {
  return useQuery({
    queryKey: queryKeys.schemaGraph,
    queryFn: () => requestJson<OpsSchemaGraph>("/ops/schema-graph"),
    staleTime: 60_000,
  });
}

export function useCollectVideosMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (channelId: number) =>
      requestJson<CollectChannelVideosResult>(`/channels/${channelId}/videos/collect`, {
        method: "POST",
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops"] }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
      ]);
    },
  });
}

export function useCollectAllTranscriptsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      collectNew = true,
      retryFailed = false,
      recheckNoTranscript = false,
    }: {
      collectNew?: boolean;
      retryFailed?: boolean;
      recheckNoTranscript?: boolean;
    } = {}) =>
      requestJson<CollectAllTranscriptsResult>("/video-tasks/transcript-collect", {
        method: "POST",
        body: {
          collectNew,
          preserveFormatting: false,
          retryFailed,
          recheckNoTranscript,
        },
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops"] }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
        queryClient.invalidateQueries({ queryKey: ["youtube-transcripts"] }),
      ]);
    },
  });
}

export function useCollectTranscriptsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      collectNew = true,
      retryFailed = false,
      recheckNoTranscript = false,
      limit,
    }: {
      channelId: number;
      collectNew?: boolean;
      retryFailed?: boolean;
      recheckNoTranscript?: boolean;
      limit: number;
    }) =>
      requestJson<CollectChannelTranscriptsResult>(
        `/channels/${channelId}/video-tasks/transcript-collect`,
        {
          method: "POST",
          body: {
            collectNew,
            limit,
            preserveFormatting: false,
            retryFailed,
            recheckNoTranscript,
          },
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops"] }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
        queryClient.invalidateQueries({ queryKey: ["youtube-transcripts"] }),
      ]);
    },
  });
}

export function useGenerateAllTranscriptCuesMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      limit,
      retryFailed = false,
      regenerateSucceeded = false,
    }: {
      limit?: number;
      retryFailed?: boolean;
      regenerateSucceeded?: boolean;
    } = {}) =>
      requestJson<GenerateAllTranscriptCuesResult>(
        "/video-tasks/transcript-cue-generate",
        {
          method: "POST",
          body: {
            limit,
            retryFailed,
            regenerateSucceeded,
          },
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops"] }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
        queryClient.invalidateQueries({ queryKey: ["youtube-transcripts"] }),
      ]);
    },
  });
}

export function useGenerateTranscriptCuesMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      retryFailed = false,
      regenerateSucceeded = false,
      limit,
    }: {
      channelId: number;
      retryFailed?: boolean;
      regenerateSucceeded?: boolean;
      limit: number;
    }) =>
      requestJson<GenerateChannelTranscriptCuesResult>(
        `/channels/${channelId}/video-tasks/transcript-cue-generate`,
        {
          method: "POST",
          body: {
            limit,
            retryFailed,
            regenerateSucceeded,
          },
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops"] }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
        queryClient.invalidateQueries({ queryKey: ["youtube-transcripts"] }),
      ]);
    },
  });
}

export function useExtractMicroEventsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      videoId,
      retryFailed = false,
      regenerateSucceeded = false,
      windowMinutes = 30,
      overlapMinutes = 5,
    }: {
      videoId: number;
    } & Partial<MicroEventExtractRequest>) =>
      requestJson<MicroEventExtractResult>(
        `/videos/${videoId}/video-tasks/micro-event-extract`,
        {
          method: "POST",
          body: {
            retryFailed,
            regenerateSucceeded,
            windowMinutes,
            overlapMinutes,
          },
        },
      ),
    onSuccess: async (_result, variables) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops"] }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.videoDetail(variables.videoId),
        }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.microEventExtraction(variables.videoId),
        }),
      ]);
    },
  });
}

export function useCreateStreamerMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name }: { name: string }) =>
      requestJson<Streamer>("/streamers", {
        method: "POST",
        body: { name },
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.streamers }),
        queryClient.invalidateQueries({ queryKey: ["ops"] }),
      ]);
    },
  });
}

export function useResolveStreamerChannelMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ streamerId, handle }: { streamerId: number; handle: string }) =>
      requestJson<ResolveYouTubeChannelResult>(
        `/streamers/${streamerId}/channels/resolve`,
        {
          method: "POST",
          body: { handle },
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops"] }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.streamers }),
      ]);
    },
  });
}

export function useRetryJobMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) =>
      requestJson<RetryPipelineJobResult>(`/pipeline/jobs/${jobId}/retry`, {
        method: "POST",
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops"] }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
        queryClient.invalidateQueries({ queryKey: ["youtube-transcripts"] }),
      ]);
    },
  });
}
