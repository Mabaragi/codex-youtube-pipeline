"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/features/query-keys";
import { requestJson } from "@/lib/api-client";
import type {
  WorkBatchDetail,
  WorkflowRunDetail,
  WorkItem,
  WorkItemDetail,
  WorkItemFilters,
  WorkItemList,
} from "@/lib/types";

export function useWorkItems(filters: WorkItemFilters = {}) {
  return useQuery({
    queryKey: queryKeys.workItems(filters),
    queryFn: () => requestJson<WorkItemList>("/ops/work-items", { query: filters }),
    refetchInterval: 5_000,
  });
}

export function useWorkItem(workItemId: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.workItem(workItemId),
    queryFn: () => requestJson<WorkItemDetail>(`/ops/work-items/${workItemId}`),
    enabled: enabled && workItemId > 0,
    refetchInterval: 5_000,
  });
}

export function useWorkBatch(batchId: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.workBatch(batchId),
    queryFn: () => requestJson<WorkBatchDetail>(`/ops/work-batches/${batchId}`),
    enabled: enabled && batchId > 0,
    refetchInterval: 5_000,
  });
}

export function useWorkflowRun(workflowId: number, enabled = true) {
  return useQuery({
    queryKey: queryKeys.workflow(workflowId),
    queryFn: () =>
      requestJson<WorkflowRunDetail>(`/ops/workflows/${workflowId}`),
    enabled: enabled && workflowId > 0,
    refetchInterval: 5_000,
  });
}

export function useRetryWorkItemMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      workItemId,
      rerunSucceeded = false,
    }: {
      workItemId: number;
      rerunSucceeded?: boolean;
    }) =>
      requestJson<WorkItem>(`/ops/work-items/${workItemId}/retry`, {
        method: "POST",
        body: { rerunSucceeded },
      }),
    onSuccess: async (item) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops", "work-items"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.workItem(item.id) }),
        queryClient.invalidateQueries({ queryKey: ["ops", "videos"] }),
      ]);
    },
  });
}

export function useCancelWorkItemMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      workItemId,
      reason = "Canceled by operator.",
    }: {
      workItemId: number;
      reason?: string;
    }) =>
      requestJson<WorkItem>(`/ops/work-items/${workItemId}/cancel`, {
        method: "POST",
        body: { reason },
      }),
    onSuccess: async (item) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["ops", "work-items"] }),
        queryClient.invalidateQueries({ queryKey: queryKeys.workItem(item.id) }),
      ]);
    },
  });
}
