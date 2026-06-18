"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { requestJson } from "@/lib/api-client";
import type {
  CollectChannelTranscriptsResult,
  CollectChannelVideosResult,
  OpsChannelList,
  OpsSchemaGraph,
  OpsSummary,
  OpsVideoList,
  OpsVideoTaskList,
  PipelineJobList,
  PipelineJobStatusFilter,
  RetryPipelineJobResult,
} from "@/lib/types";

export const queryKeys = {
  summary: ["ops", "summary"] as const,
  channels: ["ops", "channels"] as const,
  videos: (filters: Record<string, unknown>) => ["ops", "videos", filters] as const,
  tasks: (filters: Record<string, unknown>) => ["ops", "tasks", filters] as const,
  jobs: (status?: PipelineJobStatusFilter) =>
    ["pipeline", "jobs", status ?? "all"] as const,
  schemaGraph: ["ops", "schema-graph"] as const,
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
  });
}

export function useOpsVideos(filters: {
  channelId?: number;
  taskStatus?: string;
  search?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: queryKeys.videos(filters),
    queryFn: () => requestJson<OpsVideoList>("/ops/videos", { query: filters }),
  });
}

export function useOpsVideoTasks(filters: {
  channelId?: number;
  taskName?: string;
  status?: string;
  limit?: number;
  offset?: number;
}) {
  return useQuery({
    queryKey: queryKeys.tasks(filters),
    queryFn: () =>
      requestJson<OpsVideoTaskList>("/ops/video-tasks", { query: filters }),
    refetchInterval: 5_000,
  });
}

export function useRunningTranscriptTasks() {
  return useOpsVideoTasks({
    taskName: "transcript_collect",
    status: "running",
    limit: 1,
    offset: 0,
  });
}

export function usePipelineJobs(status?: PipelineJobStatusFilter) {
  return useQuery({
    queryKey: queryKeys.jobs(status),
    queryFn: () =>
      requestJson<PipelineJobList>("/pipeline/jobs", {
        query: { status, limit: 50 },
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

export function useCollectTranscriptsMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      channelId,
      retryFailed = false,
      limit = 5,
    }: {
      channelId: number;
      retryFailed?: boolean;
      limit?: number;
    }) =>
      requestJson<CollectChannelTranscriptsResult>(
        `/channels/${channelId}/video-tasks/transcript-collect`,
        {
          method: "POST",
          body: {
            limit,
            preserveFormatting: false,
            retryFailed,
          },
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops"] }),
        queryClient.invalidateQueries({ queryKey: ["pipeline"] }),
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
      ]);
    },
  });
}
