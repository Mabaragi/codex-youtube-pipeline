"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiError } from "@/features/api-error";
import { queryKeys } from "@/features/query-keys";
import type { components } from "@/generated/codex-api";
import { browserApi } from "@/lib/api";

export type ArchiveCurrent = components["schemas"]["ArchiveCurrentResponse"];
export type ArchiveVideos = components["schemas"]["ArchiveOpsVideoListResponse"];

export interface ArchiveFilters { environment: string; publishMode: "prod" | "dev"; offset?: number }

export function useArchiveCurrent(filters: ArchiveFilters, initialData?: ArchiveCurrent | null) { return useQuery({ queryKey: [...queryKeys.publishing, "current", filters], queryFn: async () => { const { data, error } = await browserApi.GET("/ops/archive/current", { params: { query: { environment: filters.environment, publishMode: filters.publishMode } } }); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined, refetchInterval: 15_000 }); }
export function useArchiveVideos(filters: ArchiveFilters, initialData?: ArchiveVideos | null) { return useQuery({ queryKey: [...queryKeys.publishing, "videos", filters], queryFn: async () => { const { data, error } = await browserApi.GET("/ops/archive/videos", { params: { query: { environment: filters.environment, limit: 50, offset: filters.offset ?? 0 } } }); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined, placeholderData: (previous) => previous, refetchInterval: 15_000 }); }

export function usePublishVideo(environment: string, publishMode: "prod" | "dev") {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: async (videoId: number) => {
    const { data, error } = await browserApi.POST("/ops/operations/archive-publish", { body: { selection: { type: "selected", videoIds: [videoId] }, includeNonEmbeddable: false, retryFailed: false, rerunSucceeded: false, timeoutSeconds: 600, publishMode, environment, variant: "control", schemaVersion: 1 } });
    if (!data) throw apiError(error); return data;
  }, onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: queryKeys.publishing }), queryClient.invalidateQueries({ queryKey: ["batches"] }), queryClient.invalidateQueries({ queryKey: ["work-items"] })]); } });
}
