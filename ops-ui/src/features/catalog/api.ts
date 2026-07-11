"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/features/query-keys";
import { requestJson } from "@/lib/api-client";
import type {
  ChannelResolveOperationRequest,
  ChannelResolveOperationResult,
  DomainEntry,
  DomainEntryAliasCreateRequest,
  DomainEntryAliasUpdateRequest,
  DomainEntryCreateRequest,
  DomainEntryFilters,
  DomainEntryList,
  DomainEntryStreamerLinkRequest,
  DomainEntryType,
  DomainEntryTypeCreateRequest,
  DomainEntryUpdateRequest,
  OpsChannelList,
  PromptCacheInvalidateRequest,
  PromptCacheInvalidateResponse,
  PromptDetail,
  PromptKey,
  PromptSummary,
  PromptVersion,
  PromptVersionCreateRequest,
  PromptVersionUpdateRequest,
  Streamer,
} from "@/lib/types";

export function useOpsChannels() {
  return useQuery({
    queryKey: queryKeys.channels,
    queryFn: () => requestJson<OpsChannelList>("/ops/channels"),
    refetchInterval: 10_000,
  });
}

export function useStreamers() {
  return useQuery({
    queryKey: queryKeys.streamers,
    queryFn: () => requestJson<Streamer[]>("/ops/streamers"),
  });
}

export function useCreateStreamerMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ name }: { name: string }) =>
      requestJson<Streamer>("/ops/streamers", {
        method: "POST",
        body: { name },
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.streamers }),
        queryClient.invalidateQueries({ queryKey: queryKeys.channels }),
      ]);
    },
  });
}

export function useResolveStreamerChannelMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Pick<ChannelResolveOperationRequest, "streamerId" | "handle">) =>
      requestJson<ChannelResolveOperationResult>(
        "/ops/operations/channel-resolve",
        {
          method: "POST",
          body: {
            ...body,
            retryFailed: false,
            rerunSucceeded: false,
            timeoutSeconds: 120,
          },
        },
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.streamers }),
        queryClient.invalidateQueries({ queryKey: queryKeys.channels }),
        queryClient.invalidateQueries({ queryKey: ["ops", "work-items"] }),
      ]);
    },
  });
}

export function useDomainEntryTypes() {
  return useQuery({
    queryKey: queryKeys.domainEntryTypes,
    queryFn: () => requestJson<DomainEntryType[]>("/ops/domain-entry-types"),
  });
}

export function useDomainEntries(filters: DomainEntryFilters) {
  return useQuery({
    queryKey: queryKeys.domainEntries(filters),
    queryFn: () =>
      requestJson<DomainEntryList>("/ops/domain-entries", { query: filters }),
  });
}

export function useCreateDomainEntryTypeMutation() {
  return useCatalogMutation<DomainEntryTypeCreateRequest, DomainEntryType>(
    "/ops/domain-entry-types",
  );
}

export function useCreateDomainEntryMutation() {
  return useCatalogMutation<DomainEntryCreateRequest, DomainEntry>(
    "/ops/domain-entries",
  );
}

export function useUpdateDomainEntryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ entryId, body }: { entryId: number; body: DomainEntryUpdateRequest }) =>
      requestJson<DomainEntry>(`/ops/domain-entries/${entryId}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: (_result, variables) =>
      invalidateDomainEntries(queryClient, variables.entryId),
  });
}

export function useArchiveDomainEntryMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (entryId: number) =>
      requestJson<DomainEntry>(`/ops/domain-entries/${entryId}`, {
        method: "DELETE",
      }),
    onSuccess: (_result, entryId) => invalidateDomainEntries(queryClient, entryId),
  });
}

export function useAddDomainEntryStreamerMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      entryId,
      body,
    }: {
      entryId: number;
      body: DomainEntryStreamerLinkRequest;
    }) =>
      requestJson<DomainEntry>(`/ops/domain-entries/${entryId}/streamers`, {
        method: "POST",
        body,
      }),
    onSuccess: (_result, variables) =>
      invalidateDomainEntries(queryClient, variables.entryId),
  });
}

export function useRemoveDomainEntryStreamerMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ entryId, streamerId }: { entryId: number; streamerId: number }) =>
      requestJson<{ success: boolean }>(
        `/ops/domain-entries/${entryId}/streamers/${streamerId}`,
        { method: "DELETE" },
      ),
    onSuccess: (_result, variables) =>
      invalidateDomainEntries(queryClient, variables.entryId),
  });
}

export function useAddDomainEntryAliasMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      entryId,
      body,
    }: {
      entryId: number;
      body: DomainEntryAliasCreateRequest;
    }) =>
      requestJson<DomainEntry>(`/ops/domain-entries/${entryId}/aliases`, {
        method: "POST",
        body,
      }),
    onSuccess: (_result, variables) =>
      invalidateDomainEntries(queryClient, variables.entryId),
  });
}

export function useUpdateDomainEntryAliasMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ aliasId, body }: { aliasId: number; body: DomainEntryAliasUpdateRequest }) =>
      requestJson(`/ops/domain-entry-aliases/${aliasId}`, {
        method: "PATCH",
        body,
      }),
    onSuccess: () => invalidateDomainEntries(queryClient),
  });
}

export function useDeleteDomainEntryAliasMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (aliasId: number) =>
      requestJson<{ success: boolean }>(`/ops/domain-entry-aliases/${aliasId}`, {
        method: "DELETE",
      }),
    onSuccess: () => invalidateDomainEntries(queryClient),
  });
}

export function usePrompts() {
  return useQuery({
    queryKey: queryKeys.prompts,
    queryFn: () => requestJson<PromptSummary[]>("/ops/prompts"),
  });
}

export function usePromptDetail(promptKey: PromptKey | null | undefined) {
  return useQuery({
    queryKey: promptKey
      ? queryKeys.promptDetail(promptKey)
      : ["ops", "prompts", "detail", "none"],
    queryFn: () => {
      if (!promptKey) {
        throw new Error("Prompt key is required.");
      }
      return requestJson<PromptDetail>(`/ops/prompts/${promptKey}`);
    },
    enabled: Boolean(promptKey),
  });
}

export function useCreatePromptVersionMutation() {
  return usePromptVersionMutation<PromptVersionCreateRequest>("POST");
}

export function useUpdatePromptVersionMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      promptKey,
      versionId,
      body,
    }: {
      promptKey: PromptKey;
      versionId: number;
      body: PromptVersionUpdateRequest;
    }) =>
      requestJson<PromptVersion>(
        `/ops/prompts/${promptKey}/versions/${versionId}`,
        { method: "PATCH", body },
      ),
    onSuccess: (_result, variables) =>
      invalidatePrompts(queryClient, variables.promptKey),
  });
}

export function usePublishPromptVersionMutation() {
  return usePromptStateMutation("publish");
}

export function useArchivePromptVersionMutation() {
  return usePromptStateMutation("archive");
}

export function useInvalidatePromptCacheMutation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PromptCacheInvalidateRequest = {}) =>
      requestJson<PromptCacheInvalidateResponse>("/ops/prompts/cache/invalidate", {
        method: "POST",
        body,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: queryKeys.prompts }),
  });
}

function useCatalogMutation<Request, Response>(path: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Request) => requestJson<Response>(path, { method: "POST", body }),
    onSuccess: () => invalidateDomainEntries(queryClient),
  });
}

function usePromptVersionMutation<Body>(method: "POST" | "PATCH") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      promptKey,
      body,
    }: {
      promptKey: PromptKey;
      body: Body;
    }) =>
      requestJson<PromptVersion>(`/ops/prompts/${promptKey}/versions`, {
        method,
        body,
      }),
    onSuccess: (_result, variables) =>
      invalidatePrompts(queryClient, variables.promptKey),
  });
}

function usePromptStateMutation(action: "publish" | "archive") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ promptKey, versionId }: { promptKey: PromptKey; versionId: number }) =>
      requestJson<PromptVersion>(
        `/ops/prompts/${promptKey}/versions/${versionId}/${action}`,
        { method: "POST" },
      ),
    onSuccess: (_result, variables) =>
      invalidatePrompts(queryClient, variables.promptKey),
  });
}

function invalidateDomainEntries(
  queryClient: ReturnType<typeof useQueryClient>,
  entryId?: number,
) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: ["ops", "domain-entries"] }),
    queryClient.invalidateQueries({ queryKey: queryKeys.domainEntryTypes }),
    ...(entryId
      ? [queryClient.invalidateQueries({ queryKey: queryKeys.domainEntry(entryId) })]
      : []),
  ]);
}

function invalidatePrompts(
  queryClient: ReturnType<typeof useQueryClient>,
  promptKey: PromptKey,
) {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: queryKeys.prompts }),
    queryClient.invalidateQueries({ queryKey: queryKeys.promptDetail(promptKey) }),
  ]);
}
