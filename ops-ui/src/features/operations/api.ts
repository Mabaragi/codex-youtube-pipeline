"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { SelectionValue } from "@/components/selection-builder";
import { apiError } from "@/features/api-error";
import type { components } from "@/generated/codex-api";
import { browserApi } from "@/lib/api";

type VideoSelection = components["schemas"]["ProcessToPublishOperationRequest"]["selection"];
export type OperationResult = components["schemas"]["OperationBatchResponse"] | components["schemas"]["WorkflowBatchResponse"];
export type StageOperation = "transcript" | "cue" | "micro" | "timeline" | "publish";

export function toVideoSelection(value: SelectionValue): VideoSelection {
  if (value.type === "selected") return { type: "selected", videoIds: value.videoIds };
  if (value.type === "channel") return { type: "channel", channelId: value.channelId ?? 0, limit: value.limit };
  if (value.type === "filter") return { type: "filter", channelId: value.channelId, search: value.search || null, limit: value.limit };
  return { type: "nextEligible", limit: value.limit };
}

export function useRunPipeline() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (selection: SelectionValue) => {
      const body: components["schemas"]["ProcessToPublishOperationRequest"] = {
        selection: toVideoSelection(selection),
        languages: ["ko", "en"],
        preserveFormatting: false,
        includeNonEmbeddable: false,
        retryFailed: false,
        microModel: "gpt-5.6-sol",
        microReasoningEffort: "high",
        microWindowMinutes: 30,
        microOverlapMinutes: 5,
        timelineModel: "gpt-5.6-luna",
        timelineReasoningEffort: "xhigh",
        publishMode: "prod",
        environment: "prod",
        variant: "control",
        schemaVersion: 1,
        transcriptFallback: {
          mode: "asr_after_grace",
          graceSeconds: 21600,
          recheckIntervalSeconds: 1800,
          model: "turbo",
          language: "ko",
          device: "cuda",
          computeType: "auto",
          chunkMinutes: 15,
          overlapSeconds: 3,
          beamSize: 5,
          vadFilter: true,
        },
      };
      const { data, error } = await browserApi.POST("/ops/workflows/process-to-publish", { body });
      if (!data) throw apiError(error);
      return data;
    },
    onSuccess: async () => invalidateExecutionQueries(queryClient),
  });
}

export function useResolveChannel() {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: async ({ streamerId, handle }: { streamerId: number; handle: string }) => requireData(await browserApi.POST("/ops/operations/channel-resolve", { body: { streamerId, handle, retryFailed: false, rerunSucceeded: false, timeoutSeconds: 600 } })), onSuccess: async () => invalidateExecutionQueries(queryClient) });
}

export function useCollectVideos() {
  const queryClient = useQueryClient();
  return useMutation({ mutationFn: async (channelIds: number[]) => requireData(await browserApi.POST("/ops/operations/video-collect", { body: { channelIds, retryFailed: false, rerunSucceeded: false, timeoutSeconds: 1800 } })), onSuccess: async () => invalidateExecutionQueries(queryClient) });
}

export function useRunStage(stage: StageOperation) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (selectionValue: SelectionValue) => {
      const selection = toVideoSelection(selectionValue);
      if (stage === "transcript") {
        return requireData(await browserApi.POST("/ops/operations/transcript-collect", { body: { selection, languages: ["ko", "en"], preserveFormatting: false, includeNonEmbeddable: false, recheckNoTranscript: false, retryFailed: false, rerunSucceeded: false, timeoutSeconds: 600 } }));
      }
      if (stage === "cue") {
        return requireData(await browserApi.POST("/ops/operations/transcript-cue-generate", { body: { selection, includeNonEmbeddable: false, retryFailed: false, rerunSucceeded: false, timeoutSeconds: 600 } }));
      }
      if (stage === "micro") {
        return requireData(await browserApi.POST("/ops/operations/micro-event-extract", { body: { selection, includeNonEmbeddable: false, retryFailed: false, rerunSucceeded: false, timeoutSeconds: 14400, model: "gpt-5.6-sol", reasoningEffort: "high", windowMinutes: 30, overlapMinutes: 5 } }));
      }
      if (stage === "timeline") {
        return requireData(await browserApi.POST("/ops/operations/timeline-compose", { body: { selection, includeNonEmbeddable: false, retryFailed: false, rerunSucceeded: false, timeoutSeconds: 7200, model: "gpt-5.6-luna", reasoningEffort: "xhigh", copyStyle: "LIGHT_FANDOM_V1" } }));
      }
      return requireData(await browserApi.POST("/ops/operations/archive-publish", { body: { selection, includeNonEmbeddable: false, retryFailed: false, rerunSucceeded: false, timeoutSeconds: 600, publishMode: "prod", environment: "prod", variant: "control", schemaVersion: 1 } }));
    },
    onSuccess: async () => invalidateExecutionQueries(queryClient),
  });
}

function requireData<T>({ data, error }: { data?: T; error?: unknown }): T {
  if (!data) throw apiError(error);
  return data;
}

async function invalidateExecutionQueries(queryClient: ReturnType<typeof useQueryClient>) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ["work-items"] }),
    queryClient.invalidateQueries({ queryKey: ["workflows"] }),
    queryClient.invalidateQueries({ queryKey: ["batches"] }),
    queryClient.invalidateQueries({ queryKey: ["events"] }),
    queryClient.invalidateQueries({ queryKey: ["videos"] }),
    queryClient.invalidateQueries({ queryKey: ["publishing"] }),
  ]);
}
