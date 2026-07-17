"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiError } from "@/features/api-error";
import { queryKeys } from "@/features/query-keys";
import type { components } from "@/generated/codex-api";
import { browserApi, operatorReasonHeader } from "@/lib/api";
import { adaptiveRefetchInterval } from "@/lib/polling";

export type VideoList = components["schemas"]["OpsVideoListResponse"];
export type VideoDetail = components["schemas"]["OpsVideoDetailResponse"];
export type Transcript = components["schemas"]["TranscriptMetadataResponse"];
export type VideoArtifacts = {
  microEvents: components["schemas"]["MicroEventExtractionDetailResponse"] | null;
  timeline: components["schemas"]["TimelineCompositionResponse"] | null;
};
export type TranscriptArtifacts = {
  metadata: components["schemas"]["TranscriptMetadataResponse"] | null;
  content: components["schemas"]["TranscriptResponse"] | null;
  cues: components["schemas"]["TranscriptCueListResponse"] | null;
  promptCues: components["schemas"]["TranscriptPromptCuesResponse"] | null;
};

export interface VideoFilters { channelId?: number; search?: string; limit?: number; offset?: number }
export interface TranscriptFilters { videoId?: string; languageCode?: string; limit?: number; offset?: number }

export function useVideos(filters: VideoFilters, initialData?: VideoList | null) {
  return useQuery({
    queryKey: queryKeys.videos(filters),
    queryFn: async () => {
      const { data, error } = await browserApi.GET("/ops/videos", { params: { query: { channelId: filters.channelId, search: filters.search, limit: filters.limit ?? 50, offset: filters.offset ?? 0 } } });
      if (!data) throw apiError(error); return data;
    },
    initialData: initialData ?? undefined,
    placeholderData: (previous) => previous,
    refetchInterval: () => adaptiveRefetchInterval([]),
  });
}

export function useVideo(id: number, initialData?: VideoDetail | null) {
  return useQuery({ queryKey: queryKeys.video(id), queryFn: async () => {
    const { data, error } = await browserApi.GET("/ops/videos/{video_id}", { params: { path: { video_id: id } } });
    if (!data) throw apiError(error); return data;
  }, initialData: initialData ?? undefined, refetchInterval: () => adaptiveRefetchInterval([]) });
}

export function useTranscripts(filters: TranscriptFilters, initialData?: Transcript[] | null) {
  return useQuery({ queryKey: queryKeys.transcripts(filters), queryFn: async () => {
    const { data, error } = await browserApi.GET("/ops/transcripts", { params: { query: { videoId: filters.videoId, languageCode: filters.languageCode, limit: filters.limit ?? 50, offset: filters.offset ?? 0 } } });
    if (!data) throw apiError(error); return data;
  }, initialData: initialData ?? undefined, placeholderData: (previous) => previous, refetchInterval: () => adaptiveRefetchInterval([]) });
}

export async function fetchVideoArtifacts(videoId: number) {
  const [micro, timeline] = await Promise.allSettled([
    browserApi.GET("/ops/videos/{video_id}/micro-events/latest", { params: { path: { video_id: videoId } } }),
    browserApi.GET("/ops/videos/{video_id}/timelines/latest", { params: { path: { video_id: videoId } } }),
  ]);
  return {
    microEvents: micro.status === "fulfilled" ? micro.value.data ?? null : null,
    timeline: timeline.status === "fulfilled" ? timeline.value.data ?? null : null,
  };
}

export function useVideoArtifacts(videoId: number, initialData?: VideoArtifacts | null) {
  return useQuery({ queryKey: [...queryKeys.video(videoId), "artifacts"], queryFn: () => fetchVideoArtifacts(videoId), initialData: initialData ?? undefined, refetchInterval: 15_000 });
}

export async function fetchTranscriptArtifacts(transcriptId: number) {
  const [metadata, content, cues, promptCues] = await Promise.allSettled([
    browserApi.GET("/ops/transcripts/{transcript_id}", { params: { path: { transcript_id: transcriptId } } }),
    browserApi.GET("/ops/transcripts/{transcript_id}/content", { params: { path: { transcript_id: transcriptId } } }),
    browserApi.GET("/ops/transcripts/{transcript_id}/cues", { params: { path: { transcript_id: transcriptId } } }),
    browserApi.GET("/ops/transcripts/{transcript_id}/prompt-cues", { params: { path: { transcript_id: transcriptId } } }),
  ]);
  return {
    metadata: metadata.status === "fulfilled" ? metadata.value.data ?? null : null,
    content: content.status === "fulfilled" ? content.value.data ?? null : null,
    cues: cues.status === "fulfilled" ? cues.value.data ?? null : null,
    promptCues: promptCues.status === "fulfilled" ? promptCues.value.data ?? null : null,
  };
}

export function useTranscriptArtifacts(transcriptId: number, initialData?: TranscriptArtifacts | null) {
  return useQuery({ queryKey: queryKeys.transcript(transcriptId), queryFn: () => fetchTranscriptArtifacts(transcriptId), initialData: initialData ?? undefined, refetchInterval: 15_000 });
}

export function useDeleteTranscript(transcriptId: number) {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: async (reason: string) => {
    const { data, error } = await browserApi.DELETE("/ops/transcripts/{transcript_id}", { params: { path: { transcript_id: transcriptId }, header: { "X-Operator-Reason": operatorReasonHeader(reason) } } });
    if (!data) throw apiError(error);
    return data;
  }, onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: ["transcripts"] }), queryClient.invalidateQueries({ queryKey: ["videos"] })]); } });
}
