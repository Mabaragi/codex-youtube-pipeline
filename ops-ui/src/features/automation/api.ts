"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { components } from "@/generated/codex-api";
import { browserApi } from "@/lib/api";
import { adaptiveRefetchInterval } from "@/lib/polling";
import { apiError } from "@/features/api-error";
import { queryKeys } from "@/features/query-keys";

export type AutomationStatus = components["schemas"]["AutomationStatusResponse"];
export type ProcessInventory = components["schemas"]["ManagedProcessInventoryResponse"];
export type IncidentList = components["schemas"]["IncidentListResponse"];
export type Incident = components["schemas"]["IncidentResponse"];
export type OpsSummary = components["schemas"]["OpsSummaryResponse"];

export function useOpsSummary(initialData?: OpsSummary | null) {
  return useQuery({
    queryKey: ["summary"],
    queryFn: async () => {
      const { data, error } = await browserApi.GET("/ops/summary");
      if (!data) throw apiError(error);
      return data;
    },
    initialData: initialData ?? undefined,
    refetchInterval: 15_000,
  });
}

export function useAutomationStatus(initialData?: AutomationStatus | null) {
  return useQuery({
    queryKey: queryKeys.automation,
    queryFn: async () => {
      const { data, error } = await browserApi.GET("/ops/automation/status");
      if (!data) throw apiError(error);
      return data;
    },
    initialData: initialData ?? undefined,
    refetchInterval: (query) => adaptiveRefetchInterval([query.state.data?.runtime.state]),
  });
}

export function useProcessInventory(initialData?: ProcessInventory | null) {
  return useQuery({
    queryKey: queryKeys.processes,
    queryFn: async () => {
      const { data, error } = await browserApi.GET("/ops/automation/processes");
      if (!data) throw apiError(error);
      return data;
    },
    initialData: initialData ?? undefined,
    refetchInterval: () => adaptiveRefetchInterval([]),
  });
}

export interface IncidentFilters {
  state?: "open" | "acknowledged" | "resolved" | "suppressed";
  limit?: number;
}

export function useIncidents(filters: IncidentFilters, initialData?: IncidentList | null) {
  return useQuery({
    queryKey: queryKeys.incidents(filters),
    queryFn: async () => {
      const { data, error } = await browserApi.GET("/ops/incidents", {
        params: { query: { state: filters.state, limit: filters.limit ?? 100 } },
      });
      if (!data) throw apiError(error);
      return data;
    },
    initialData: initialData ?? undefined,
    refetchInterval: (query) => adaptiveRefetchInterval(query.state.data?.items ?? []),
  });
}

export function useIncident(id: number, initialData?: Incident | null) {
  return useQuery({
    queryKey: queryKeys.incident(id),
    queryFn: async () => {
      const { data, error } = await browserApi.GET("/ops/incidents/{incident_id}", {
        params: { path: { incident_id: id } },
      });
      if (!data) throw apiError(error);
      return data;
    },
    initialData: initialData ?? undefined,
    refetchInterval: (query) => adaptiveRefetchInterval([query.state.data?.state]),
  });
}

export function useRuntimeTransition(action: "drain" | "mark-stopped" | "resume") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (reason: string) => {
      const path = `/ops/automation/runtime/${action}` as const;
      const result = action === "drain"
        ? await browserApi.POST("/ops/automation/runtime/drain", { body: { reason } })
        : action === "resume"
          ? await browserApi.POST("/ops/automation/runtime/resume", { body: { reason } })
          : await browserApi.POST("/ops/automation/runtime/mark-stopped", { body: { reason } });
      if (!result.data) throw apiError(result.error, `${path} 요청에 실패했습니다.`);
      return result.data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.automation });
    },
  });
}

export function useUpdateIncident(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: { state: "acknowledged" | "resolved" | "suppressed"; note: string }) => {
      const { data, error } = await browserApi.PATCH("/ops/incidents/{incident_id}", {
        params: { path: { incident_id: id } }, body,
      });
      if (!data) throw apiError(error);
      return data;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.incident(id) }),
        queryClient.invalidateQueries({ queryKey: ["incidents"] }),
      ]);
    },
  });
}

export function useIncidentAction(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ action, parameters, idempotencyKey }: { action: "retry" | "recover_lease" | "extend_timeout" | "set_temporary_concurrency"; parameters: Record<string, unknown>; idempotencyKey: string }) => {
      const { data, error } = await browserApi.POST("/ops/incidents/{incident_id}/actions", {
        params: { path: { incident_id: id } },
        body: { action, parameters, idempotencyKey },
      });
      if (!data) throw apiError(error);
      return data;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.incident(id) }),
        queryClient.invalidateQueries({ queryKey: ["incidents"] }),
        queryClient.invalidateQueries({ queryKey: ["work-items"] }),
        queryClient.invalidateQueries({ queryKey: ["workflows"] }),
      ]);
    },
  });
}
