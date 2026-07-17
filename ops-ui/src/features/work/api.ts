"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiError } from "@/features/api-error";
import { queryKeys } from "@/features/query-keys";
import type { components } from "@/generated/codex-api";
import { browserApi } from "@/lib/api";
import { adaptiveRefetchInterval } from "@/lib/polling";

export type WorkItemList = components["schemas"]["WorkItemListResponse"];
export type WorkItemDetail = components["schemas"]["WorkItemDetailResponse"];
export type WorkflowList = components["schemas"]["WorkflowRunListResponse"];
export type WorkflowDetail = components["schemas"]["WorkflowRunDetailResponse"];
export type BatchList = components["schemas"]["WorkBatchListResponse"];
export type BatchDetail = components["schemas"]["WorkBatchDetailResponse"];

export interface WorkFilters { taskType?: string; status?: string; cursor?: number; limit?: number }
export interface WorkflowFilters { workflowType?: string; status?: string; videoId?: number; cursor?: number; limit?: number }
export interface BatchFilters { operationType?: string; status?: string; cursor?: number; limit?: number }

export function useWorkItems(filters: WorkFilters, initialData?: WorkItemList | null) {
  return useQuery({ queryKey: queryKeys.workItems(filters), queryFn: async () => {
    const { data, error } = await browserApi.GET("/ops/work-items", { params: { query: { taskType: filters.taskType, status: filters.status as never, cursor: filters.cursor, limit: filters.limit ?? 50 } } });
    if (!data) throw apiError(error); return data;
  }, initialData: initialData ?? undefined, placeholderData: (previous) => previous, refetchInterval: (query) => adaptiveRefetchInterval(query.state.data?.items ?? []) });
}

export function useWorkflows(filters: WorkflowFilters, initialData?: WorkflowList | null) {
  return useQuery({ queryKey: queryKeys.workflows(filters), queryFn: async () => {
    const { data, error } = await browserApi.GET("/ops/workflows", { params: { query: { workflowType: filters.workflowType, status: filters.status as never, videoId: filters.videoId, cursor: filters.cursor, limit: filters.limit ?? 50 } } });
    if (!data) throw apiError(error); return data;
  }, initialData: initialData ?? undefined, placeholderData: (previous) => previous, refetchInterval: (query) => adaptiveRefetchInterval(query.state.data?.items ?? []) });
}

export function useBatches(filters: BatchFilters, initialData?: BatchList | null) {
  return useQuery({ queryKey: queryKeys.batches(filters), queryFn: async () => {
    const { data, error } = await browserApi.GET("/ops/work-batches", { params: { query: { operationType: filters.operationType, status: filters.status as never, cursor: filters.cursor, limit: filters.limit ?? 50 } } });
    if (!data) throw apiError(error); return data;
  }, initialData: initialData ?? undefined, placeholderData: (previous) => previous, refetchInterval: (query) => adaptiveRefetchInterval(query.state.data?.items ?? []) });
}

export function useWorkItem(id: number, initialData?: WorkItemDetail | null) { return useQuery({ queryKey: queryKeys.workItem(id), queryFn: async () => { const { data, error } = await browserApi.GET("/ops/work-items/{work_item_id}", { params: { path: { work_item_id: id } } }); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined, refetchInterval: (query) => adaptiveRefetchInterval([query.state.data?.status]) }); }
export function useWorkflow(id: number, initialData?: WorkflowDetail | null) { return useQuery({ queryKey: queryKeys.workflow(id), queryFn: async () => { const { data, error } = await browserApi.GET("/ops/workflows/{workflow_run_id}", { params: { path: { workflow_run_id: id } } }); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined, refetchInterval: (query) => adaptiveRefetchInterval([query.state.data?.status]) }); }
export function useBatch(id: number, initialData?: BatchDetail | null) { return useQuery({ queryKey: queryKeys.batch(id), queryFn: async () => { const { data, error } = await browserApi.GET("/ops/work-batches/{batch_id}", { params: { path: { batch_id: id } } }); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined, refetchInterval: (query) => adaptiveRefetchInterval([query.state.data?.status]) }); }

export function useRetryWorkItem(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (rerunSucceeded: boolean) => {
      const { data, error } = await browserApi.POST("/ops/work-items/{work_item_id}/retry", { params: { path: { work_item_id: id } }, body: { rerunSucceeded } });
      if (!data) throw apiError(error);
      return data;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.workItem(id) }),
        queryClient.invalidateQueries({ queryKey: ["work-items"] }),
      ]);
    },
  });
}
export function useCancelWorkItem(id: number) { const queryClient = useQueryClient(); return useMutation({ mutationFn: async (reason: string) => { const { data, error } = await browserApi.POST("/ops/work-items/{work_item_id}/cancel", { params: { path: { work_item_id: id } }, body: { reason } }); if (!data) throw apiError(error); return data; }, onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: queryKeys.workItem(id) }), queryClient.invalidateQueries({ queryKey: ["work-items"] })]); } }); }
