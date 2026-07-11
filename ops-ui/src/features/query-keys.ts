import type { PromptKey } from "@/lib/types";

export const queryKeys = {
  summary: ["ops", "summary"] as const,
  channels: ["ops", "channels"] as const,
  videos: (filters: Record<string, unknown>) => ["ops", "videos", filters] as const,
  videoDetail: (videoId: number) => ["ops", "videos", videoId] as const,
  workItems: (filters: Record<string, unknown>) =>
    ["ops", "work-items", filters] as const,
  workItem: (workItemId: number) => ["ops", "work-items", workItemId] as const,
  workBatch: (batchId: number) => ["ops", "work-batches", batchId] as const,
  workflow: (workflowId: number) => ["ops", "workflows", workflowId] as const,
  events: (filters: Record<string, unknown>) => ["ops", "events", filters] as const,
  streamers: ["ops", "streamers"] as const,
  codexUsage: (filters: Record<string, unknown>) =>
    ["ops", "codex-usage", filters] as const,
  codexUsageByVideo: (filters: Record<string, unknown>) =>
    ["ops", "codex-usage", "by-video", filters] as const,
  codexUsageByJob: (filters: Record<string, unknown>) =>
    ["ops", "codex-usage", "by-job", filters] as const,
  domainEntryTypes: ["ops", "domain-entry-types"] as const,
  domainEntries: (filters: Record<string, unknown>) =>
    ["ops", "domain-entries", filters] as const,
  domainEntry: (entryId: number) => ["ops", "domain-entries", entryId] as const,
  prompts: ["ops", "prompts"] as const,
  promptDetail: (promptKey: PromptKey) => ["ops", "prompts", promptKey] as const,
  schemaGraph: ["ops", "schema-graph"] as const,
  transcriptContent: (transcriptId: number) =>
    ["ops", "transcripts", transcriptId, "content"] as const,
  transcriptCues: (transcriptId: number) =>
    ["ops", "transcripts", transcriptId, "cues"] as const,
  microEventExtraction: (videoId: number) =>
    ["ops", "videos", videoId, "micro-events", "latest"] as const,
  timelineComposition: (videoId: number) =>
    ["ops", "videos", videoId, "timelines", "latest"] as const,
  archiveCurrent: (environment: string | undefined) =>
    ["ops", "archive", "current", environment ?? "default"] as const,
  archiveVideos: (filters: Record<string, unknown>) =>
    ["ops", "archive", "videos", filters] as const,
};
