"use client";

import { useQuery } from "@tanstack/react-query";
import { queryKeys } from "@/features/query-keys";
import { requestJson } from "@/lib/api-client";
import type {
  CodexUsageByJobFilters,
  CodexUsageByJobList,
  CodexUsageByVideoFilters,
  CodexUsageByVideoList,
  CodexUsageFilters,
  CodexUsageList,
  OperationEventFilters,
  OperationEventList,
  OpsSchemaGraph,
  OpsSummary,
} from "@/lib/types";

export function useOpsSummary() {
  return useQuery({
    queryKey: queryKeys.summary,
    queryFn: () => requestJson<OpsSummary>("/ops/summary"),
    refetchInterval: 10_000,
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

export function useCodexUsageByJob(
  filters: CodexUsageByJobFilters,
  enabled = true,
) {
  return useQuery({
    queryKey: queryKeys.codexUsageByJob(filters),
    queryFn: () =>
      requestJson<CodexUsageByJobList>("/ops/codex-usage/by-job", {
        query: filters,
      }),
    enabled,
    refetchInterval: enabled ? 10_000 : false,
  });
}

export function useSchemaGraph() {
  return useQuery({
    queryKey: queryKeys.schemaGraph,
    queryFn: () => requestJson<OpsSchemaGraph>("/ops/schema-graph"),
    staleTime: 60_000,
  });
}
