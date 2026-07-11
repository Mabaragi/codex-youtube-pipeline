"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/features/query-keys";
import { requestJson } from "@/lib/api-client";
import type {
  ArchiveCurrent,
  ArchiveOpsVideoFilters,
  ArchiveOpsVideoList,
  ArchivePublishOperationRequest,
  OperationBatchResult,
} from "@/lib/types";

export function useArchiveCurrent(environment?: string) {
  return useQuery({
    queryKey: queryKeys.archiveCurrent(environment),
    queryFn: () =>
      requestJson<ArchiveCurrent>("/ops/archive/current", {
        query: environment ? { environment } : undefined,
      }),
    refetchInterval: 10_000,
  });
}

export function useArchiveVideos(filters: ArchiveOpsVideoFilters) {
  return useQuery({
    queryKey: queryKeys.archiveVideos(filters),
    queryFn: () =>
      requestJson<ArchiveOpsVideoList>("/ops/archive/videos", { query: filters }),
    refetchInterval: 10_000,
  });
}

export function usePublishArchiveMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ArchivePublishOperationRequest) =>
      requestJson<OperationBatchResult>("/ops/operations/archive-publish", {
        method: "POST",
        body,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops", "archive"] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "work-items"] }),
        queryClient.invalidateQueries({ queryKey: ["ops", "videos"] }),
      ]);
    },
  });
}
