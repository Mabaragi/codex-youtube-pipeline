import type { OperationEvent, OperationEventFilters } from "@/lib/types";

export function logsHref(filters: Partial<OperationEventFilters> = {}): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `/logs?${query}` : "/logs";
}

export function eventSubjectLabel(event: OperationEvent): string {
  if (event.subjectType && event.subjectId !== null && event.subjectId !== undefined) {
    return `${event.subjectType} #${event.subjectId}`;
  }
  return event.externalKey ?? "-";
}

export function eventLogLinkFilters(
  event: OperationEvent,
): Partial<OperationEventFilters> {
  if (event.workItemId !== null && event.workItemId !== undefined) {
    return { workItemId: event.workItemId };
  }
  if (event.workBatchId !== null && event.workBatchId !== undefined) {
    return { workBatchId: event.workBatchId };
  }
  if (event.jobId !== null && event.jobId !== undefined) {
    return { jobId: event.jobId };
  }
  if (event.videoTaskId !== null && event.videoTaskId !== undefined) {
    return { videoTaskId: event.videoTaskId };
  }
  if (event.channelId !== null && event.channelId !== undefined) {
    return { channelId: event.channelId };
  }
  return { eventType: event.eventType };
}
