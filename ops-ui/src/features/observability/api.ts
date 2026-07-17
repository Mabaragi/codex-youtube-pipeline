"use client";

import { useQuery } from "@tanstack/react-query";

import { apiError } from "@/features/api-error";
import { queryKeys } from "@/features/query-keys";
import type { components } from "@/generated/codex-api";
import { browserApi } from "@/lib/api";
import { adaptiveRefetchInterval } from "@/lib/polling";

export type EventList = components["schemas"]["OperationEventListResponse"];
export type UsageList = components["schemas"]["CodexUsageListResponse"];
export type SchemaGraph = components["schemas"]["OpsSchemaGraphResponse"];

export interface EventFilters { severity?: string; eventType?: string; cursor?: number }
export interface UsageFilters { source?: string; status?: string; model?: string; cursor?: number }

export function useEvents(filters: EventFilters, initialData?: EventList | null) { return useQuery({ queryKey: queryKeys.events(filters), queryFn: async () => { const { data, error } = await browserApi.GET("/ops/events", { params: { query: { severity: filters.severity as never, eventType: filters.eventType, cursor: filters.cursor, limit: 100 } } }); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined, placeholderData: (previous) => previous, refetchInterval: () => adaptiveRefetchInterval([]) }); }
export function useUsage(filters: UsageFilters, initialData?: UsageList | null) { return useQuery({ queryKey: [...queryKeys.usage, filters], queryFn: async () => { const { data, error } = await browserApi.GET("/ops/codex-usage", { params: { query: { source: filters.source, status: filters.status as never, model: filters.model, cursor: filters.cursor, limit: 100 } } }); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined, placeholderData: (previous) => previous, refetchInterval: 15_000 }); }
export function useSchemaGraph(initialData?: SchemaGraph | null) { return useQuery({ queryKey: queryKeys.schema, queryFn: async () => { const { data, error } = await browserApi.GET("/ops/schema-graph"); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined }); }
