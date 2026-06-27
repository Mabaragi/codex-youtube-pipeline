"use client";

import { AlertTriangle, Captions, Loader2 } from "lucide-react";
import Link from "next/link";
import type { TranscriptCollectionLockState } from "@/lib/transcript-collection-lock";

export function TranscriptCollectionStatus({
  state,
  className = "",
  showIdle = false,
}: {
  state: TranscriptCollectionLockState;
  className?: string;
  showIdle?: boolean;
}) {
  if (state.status === "idle" && !showIdle) {
    return null;
  }

  const Icon =
    state.status === "checking"
      ? Loader2
      : state.status === "unavailable"
        ? AlertTriangle
        : Captions;
  const tone = statusTone(state.status);

  return (
    <div
      className={`${className} flex flex-wrap items-center justify-between gap-3 rounded border p-3 text-sm ${tone}`}
      role={state.status === "unavailable" ? "alert" : "status"}
      aria-live="polite"
    >
      <div className="flex min-w-0 items-center gap-2">
        <Icon aria-hidden="true" size={16} />
        <div className="min-w-0">
          <div className="font-medium">{statusLabel(state.status)}</div>
          <div className="text-xs">{state.message}</div>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs">
        {state.runningBatchCount > 0 ? (
          <Link
            className="ops-button"
            href="/jobs?status=running&step=transcript_collect_batch&limit=50"
          >
            batches {state.runningBatchCount}
          </Link>
        ) : null}
        {state.runningTaskCount > 0 ? (
          <Link
            className="ops-button"
            href="/tasks?status=running&taskName=transcript_collect&limit=100"
          >
            tasks {state.runningTaskCount}
          </Link>
        ) : null}
        {state.status === "idle" ? <span className="text-slate-500">limit 1</span> : null}
      </div>
    </div>
  );
}

function statusLabel(status: TranscriptCollectionLockState["status"]) {
  if (status === "running") {
    return "Transcript collection running";
  }
  if (status === "checking") {
    return "Transcript collection checking";
  }
  if (status === "unavailable") {
    return "Transcript collection unavailable";
  }
  return "Transcript collection ready";
}

function statusTone(status: TranscriptCollectionLockState["status"]) {
  if (status === "running" || status === "checking") {
    return "border-amber-200 bg-amber-50 text-amber-900";
  }
  if (status === "unavailable") {
    return "border-red-200 bg-red-50 text-red-800";
  }
  return "border-slate-200 bg-slate-50 text-slate-700";
}
