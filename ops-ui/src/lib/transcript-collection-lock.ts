"use client";

import type { OpsVideoTask, OpsVideoTaskList, PipelineJobList } from "@/lib/types";

export type TranscriptCollectionLockStatus =
  | "idle"
  | "checking"
  | "running"
  | "unavailable";

export type TranscriptCollectionLockState = {
  status: TranscriptCollectionLockStatus;
  isLocked: boolean;
  isChecking: boolean;
  cannotVerify: boolean;
  isRunning: boolean;
  isMutationPending: boolean;
  runningTaskCount: number;
  runningBatchCount: number;
  runningTask: OpsVideoTask | null;
  runningBatch: PipelineJobList["items"][number] | null;
  message: string;
};

export function buildTranscriptCollectionLock({
  runningTasks,
  runningBatches,
  tasksLoading,
  batchesLoading,
  tasksError,
  batchesError,
  mutationPending = false,
}: {
  runningTasks: OpsVideoTaskList | undefined;
  runningBatches: PipelineJobList | undefined;
  tasksLoading: boolean;
  batchesLoading: boolean;
  tasksError: boolean;
  batchesError: boolean;
  mutationPending?: boolean;
}): TranscriptCollectionLockState {
  const runningTaskCount = runningTasks?.total ?? 0;
  const runningBatchCount = runningBatches?.items.length ?? 0;
  const isChecking = tasksLoading || batchesLoading;
  const cannotVerify = tasksError || batchesError;
  const hasRunningWork = runningTaskCount > 0 || runningBatchCount > 0;
  const isRunning = mutationPending || hasRunningWork;
  const status = transcriptCollectionStatus({
    isRunning,
    isChecking,
    cannotVerify,
  });

  return {
    status,
    isLocked: status !== "idle",
    isChecking,
    cannotVerify,
    isRunning,
    isMutationPending: mutationPending,
    runningTaskCount,
    runningBatchCount,
    runningTask: runningTasks?.items[0] ?? null,
    runningBatch: runningBatches?.items[0] ?? null,
    message: transcriptCollectionMessage({
      status,
      runningTaskCount,
      runningBatchCount,
      mutationPending,
    }),
  };
}

export function transcriptCollectionActionTitle(
  state: TranscriptCollectionLockState,
) {
  if (state.status === "running") {
    return "Transcript collection is already running";
  }
  if (state.status === "checking") {
    return "Checking transcript collection state";
  }
  if (state.status === "unavailable") {
    return "Cannot verify transcript collection state";
  }
  return "Transcript collection is ready";
}

function transcriptCollectionStatus({
  isRunning,
  isChecking,
  cannotVerify,
}: {
  isRunning: boolean;
  isChecking: boolean;
  cannotVerify: boolean;
}): TranscriptCollectionLockStatus {
  if (isRunning) {
    return "running";
  }
  if (isChecking) {
    return "checking";
  }
  if (cannotVerify) {
    return "unavailable";
  }
  return "idle";
}

function transcriptCollectionMessage({
  status,
  runningTaskCount,
  runningBatchCount,
  mutationPending,
}: {
  status: TranscriptCollectionLockStatus;
  runningTaskCount: number;
  runningBatchCount: number;
  mutationPending: boolean;
}) {
  if (status === "running") {
    if (mutationPending && runningTaskCount === 0 && runningBatchCount === 0) {
      return "Transcript collection request is running. Transcript actions are disabled.";
    }
    return "Transcript collection is running. Transcript actions are disabled.";
  }
  if (status === "checking") {
    return "Checking transcript collection state…";
  }
  if (status === "unavailable") {
    return "Cannot verify transcript collection state. Transcript actions are disabled.";
  }
  return "Transcript collection is ready.";
}
