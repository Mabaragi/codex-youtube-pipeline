"use client";

import { useQuery } from "@tanstack/react-query";

import { apiError } from "@/features/api-error";
import { queryKeys } from "@/features/query-keys";
import type { components } from "@/generated/codex-api";
import { browserApi } from "@/lib/api";

export type ChannelList = components["schemas"]["OpsChannelListResponse"];
export type Streamer = components["schemas"]["StreamerResponse"];
export type DomainEntryList = components["schemas"]["DomainEntryListResponse"];
export type PromptSummary = components["schemas"]["PromptSummaryResponse"];

export function useChannels(initialData?: ChannelList | null) { return useQuery({ queryKey: queryKeys.channels, queryFn: async () => { const { data, error } = await browserApi.GET("/ops/channels"); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined, refetchInterval: 15_000 }); }
export function useStreamers(initialData?: Streamer[] | null) { return useQuery({ queryKey: queryKeys.streamers, queryFn: async () => { const { data, error } = await browserApi.GET("/ops/streamers"); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined, refetchInterval: 15_000 }); }
export function useDomainEntries(initialData?: DomainEntryList | null) { return useQuery({ queryKey: queryKeys.knowledge(), queryFn: async () => { const { data, error } = await browserApi.GET("/ops/domain-entries", { params: { query: { active: true, limit: 200 } } }); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined }); }
export function usePrompts(initialData?: PromptSummary[] | null) { return useQuery({ queryKey: queryKeys.prompts, queryFn: async () => { const { data, error } = await browserApi.GET("/ops/prompts"); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined }); }
