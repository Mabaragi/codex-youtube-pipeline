"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { apiError } from "@/features/api-error";
import { queryKeys } from "@/features/query-keys";
import type { components } from "@/generated/codex-api";
import { browserApi, operatorReasonHeader } from "@/lib/api";

import {
  type PublicationStatusFilter,
  parsePublicationStatus,
  publicationStatusFilters,
} from "./filters";

export { parsePublicationStatus, publicationStatusFilters };
export type { PublicationStatusFilter };

export type ArchiveCurrent = components["schemas"]["ArchiveCurrentResponse"];
export type ArchiveVideos = components["schemas"]["ArchiveOpsVideoListResponse"];
export type PublicationStatusList = components["schemas"]["PublicationStatusListResponse"];
export type PublicationStatus = components["schemas"]["PublicationStatusResponse"];
export type PublicationConnectionList = components["schemas"]["PublicationConnectionListResponse"];
export type PublicationConnection = components["schemas"]["PublicationConnectionResponse"];
export type ObjectDestination = components["schemas"]["ObjectDestinationResponse"];
export type CatalogDestination = components["schemas"]["CatalogDestinationResponse"];
export type PublishProfile = components["schemas"]["PublishProfileSummaryResponse"];
export type PublishProfileDetail = components["schemas"]["PublishProfileDetailResponse"];
type ObjectDestinationCreate = components["schemas"]["ObjectDestinationCreateRequest"];
type CatalogDestinationCreate = components["schemas"]["CatalogDestinationCreateRequest"];
type PublishProfileCreate = components["schemas"]["PublishProfileCreateRequest"];
type PublishProfileRevisionCreate = components["schemas"]["PublishProfileRevisionCreateRequest"];

export interface ArchiveFilters { environment: string; publishMode: "prod" | "dev"; offset?: number; streamerId?: number; profileId?: number }
export interface PublicationFilters { environment: string; publishMode: "prod" | "dev"; offset?: number; streamerId?: number; profileId?: number; status?: PublicationStatusFilter }

export function useArchiveCurrent(filters: ArchiveFilters, initialData?: ArchiveCurrent | null) { return useQuery({ queryKey: [...queryKeys.publishing, "current", filters], queryFn: async () => { const { data, error } = await browserApi.GET("/ops/archive/current", { params: { query: { environment: filters.environment, publishMode: filters.publishMode } } }); if (!data) throw apiError(error); return data; }, initialData: initialData ?? undefined, refetchInterval: 15_000 }); }
export function useArchiveVideos(filters: ArchiveFilters, initialData?: ArchiveVideos | null) { return useQuery({ queryKey: [...queryKeys.publishing, "videos", filters], queryFn: async () => {
  const query = { environment: filters.environment, limit: 50, offset: filters.offset ?? 0, ...(filters.streamerId ? { streamerId: filters.streamerId } : {}), ...(filters.profileId ? { profileId: filters.profileId } : {}) };
  const { data, error } = await browserApi.GET("/ops/archive/videos", { params: { query } });
  if (!data) throw apiError(error); return data;
}, initialData: initialData ?? undefined, placeholderData: (previous) => previous, refetchInterval: 15_000 }); }

export function usePublicationStatuses(filters: PublicationFilters, initialData?: PublicationStatusList | null) { return useQuery({ queryKey: [...queryKeys.publishing, "publications", filters], queryFn: async () => {
  const { data, error } = await browserApi.GET("/ops/publish/publications", { params: { query: { environment: filters.environment, publishMode: filters.publishMode, limit: 50, offset: filters.offset ?? 0, ...(filters.streamerId ? { streamerId: filters.streamerId } : {}), ...(filters.profileId ? { profileId: filters.profileId } : {}), ...(filters.status ? { status: filters.status } : {}) } } });
  if (!data) throw apiError(error); return data;
}, initialData: initialData ?? undefined, placeholderData: (previous) => previous, refetchInterval: 15_000 }); }

export function usePublishVideo(environment: string, publishMode: "prod" | "dev") {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: async (videoId: number) => {
    const { data, error } = await browserApi.POST("/ops/operations/archive-publish", { body: { selection: { type: "selected", videoIds: [videoId] }, includeNonEmbeddable: false, retryFailed: false, rerunSucceeded: false, timeoutSeconds: 600, publishMode, environment, variant: "control", schemaVersion: 1 } });
    if (!data) throw apiError(error); return data;
  }, onSuccess: async () => { await Promise.all([queryClient.invalidateQueries({ queryKey: queryKeys.publishing }), queryClient.invalidateQueries({ queryKey: ["batches"] }), queryClient.invalidateQueries({ queryKey: ["work-items"] })]); } });
}

const publicationConfigurationKey = [...queryKeys.publishing, "configuration"] as const;

export function usePublicationConnections() {
  return useQuery({ queryKey: [...publicationConfigurationKey, "connections"], queryFn: async () => {
    const { data, error } = await browserApi.GET("/ops/publish/connections");
    if (!data) throw apiError(error);
    return data;
  }, refetchInterval: 15_000, placeholderData: (previous) => previous });
}

export function useObjectDestinations() {
  return useQuery({ queryKey: [...publicationConfigurationKey, "object-destinations"], queryFn: async () => {
    const { data, error } = await browserApi.GET("/ops/publish/object-destinations");
    if (!data) throw apiError(error);
    return data;
  }, refetchInterval: 15_000, placeholderData: (previous) => previous });
}

export function useCatalogDestinations() {
  return useQuery({ queryKey: [...publicationConfigurationKey, "catalog-destinations"], queryFn: async () => {
    const { data, error } = await browserApi.GET("/ops/publish/catalog-destinations");
    if (!data) throw apiError(error);
    return data;
  }, refetchInterval: 15_000, placeholderData: (previous) => previous });
}

export function usePublishProfiles() {
  return useQuery({ queryKey: [...publicationConfigurationKey, "profiles"], queryFn: async () => {
    const { data, error } = await browserApi.GET("/ops/publish/profiles");
    if (!data) throw apiError(error);
    return data;
  }, refetchInterval: 15_000, placeholderData: (previous) => previous });
}

export function usePublishProfileDetail(profileId: number | null) {
  return useQuery({ queryKey: [...publicationConfigurationKey, "profiles", profileId], enabled: profileId !== null, queryFn: async () => {
    if (profileId === null) throw new Error("Select a publication profile first.");
    const { data, error } = await browserApi.GET("/ops/publish/profiles/{profileId}", { params: { path: { profileId } } });
    if (!data) throw apiError(error);
    return data;
  }, placeholderData: (previous) => previous });
}

async function invalidatePublicationConfiguration(queryClient: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: publicationConfigurationKey }),
    queryClient.invalidateQueries({ queryKey: queryKeys.streamers }),
  ]);
}

export function useCreateObjectDestination() {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: async ({ body, reason }: { body: ObjectDestinationCreate; reason: string }) => {
    const { data, error } = await browserApi.POST("/ops/publish/object-destinations", { body, params: { header: { "X-Operator-Reason": operatorReasonHeader(reason) } } });
    if (!data) throw apiError(error);
    return data;
  }, onSuccess: () => invalidatePublicationConfiguration(queryClient) });
}

export function useCreateCatalogDestination() {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: async ({ body, reason }: { body: CatalogDestinationCreate; reason: string }) => {
    const { data, error } = await browserApi.POST("/ops/publish/catalog-destinations", { body, params: { header: { "X-Operator-Reason": operatorReasonHeader(reason) } } });
    if (!data) throw apiError(error);
    return data;
  }, onSuccess: () => invalidatePublicationConfiguration(queryClient) });
}

export function useCreatePublishProfile() {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: async ({ body, reason }: { body: PublishProfileCreate; reason: string }) => {
    const { data, error } = await browserApi.POST("/ops/publish/profiles", { body, params: { header: { "X-Operator-Reason": operatorReasonHeader(reason) } } });
    if (!data) throw apiError(error);
    return data;
  }, onSuccess: () => invalidatePublicationConfiguration(queryClient) });
}

export function useCreatePublishProfileRevision(profileId: number) {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: async ({ body, reason }: { body: PublishProfileRevisionCreate; reason: string }) => {
    const { data, error } = await browserApi.POST("/ops/publish/profiles/{profileId}/revisions", { params: { path: { profileId }, header: { "X-Operator-Reason": operatorReasonHeader(reason) } }, body });
    if (!data) throw apiError(error);
    return data;
  }, onSuccess: () => invalidatePublicationConfiguration(queryClient) });
}

export function useActivatePublishProfileRevision(profileId: number) {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: async ({ revisionId, reason }: { revisionId: number; reason: string }) => {
    const { data, error } = await browserApi.POST("/ops/publish/profiles/{profileId}/revisions/{revisionId}/activate", { params: { path: { profileId, revisionId }, header: { "X-Operator-Reason": operatorReasonHeader(reason) } } });
    if (!data) throw apiError(error);
    return data;
  }, onSuccess: () => invalidatePublicationConfiguration(queryClient) });
}

export type PublicationStage = "artifactBuild" | "objectDeliver" | "catalogPublish" | "publicationBuild" | "pointerPublish";
export type PublicationStageResult = components["schemas"]["PublicationStageResponse"];
type ArtifactBuildStageRequest = components["schemas"]["ArchiveArtifactBuildOperationRequest"];
type RoutedPublicationStageRequest = components["schemas"]["PublicationArtifactStageRequest"];
type PublicationBuildStageRequest = components["schemas"]["PublicationBuildStageRequest"];
type PointerPublicationStageRequest = components["schemas"]["PublicationPointerStageRequest"];
export type PublicationStageCommand =
  | { stage: "artifactBuild"; body: ArtifactBuildStageRequest }
  | { stage: "objectDeliver" | "catalogPublish"; body: RoutedPublicationStageRequest }
  | { stage: "publicationBuild"; body: PublicationBuildStageRequest }
  | { stage: "pointerPublish"; body: PointerPublicationStageRequest };

async function postPublicationStage(command: PublicationStageCommand): Promise<PublicationStageResult> {
  switch (command.stage) {
    case "artifactBuild": {
      const { data, error } = await browserApi.POST("/ops/operations/archive-artifact-build", { body: command.body });
      if (!data) throw apiError(error); return data;
    }
    case "objectDeliver": {
      const { data, error } = await browserApi.POST("/ops/operations/archive-object-deliver", { body: command.body });
      if (!data) throw apiError(error); return data;
    }
    case "catalogPublish": {
      const { data, error } = await browserApi.POST("/ops/operations/archive-catalog-publish", { body: command.body });
      if (!data) throw apiError(error); return data;
    }
    case "publicationBuild": {
      const { data, error } = await browserApi.POST("/ops/operations/archive-publication-build", { body: command.body });
      if (!data) throw apiError(error); return data;
    }
    case "pointerPublish": {
      const { data, error } = await browserApi.POST("/ops/operations/archive-pointer-publish", { body: command.body });
      if (!data) throw apiError(error); return data;
    }
  }
}

export function useRunPublicationStage() {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: postPublicationStage, onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.publishing });
  } });
}
