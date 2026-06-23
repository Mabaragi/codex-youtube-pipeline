import type { components, paths } from "@/generated/codex-api";

export type OpsSummary = components["schemas"]["OpsSummaryResponse"];
export type OpsChannelList = components["schemas"]["OpsChannelListResponse"];
export type OpsChannel = components["schemas"]["OpsChannelResponse"];
export type OpsVideoList = components["schemas"]["OpsVideoListResponse"];
export type OpsVideo = components["schemas"]["OpsVideoResponse"];
export type OpsVideoDetail = components["schemas"]["OpsVideoDetailResponse"];
export type OpsVideoTaskList = components["schemas"]["OpsVideoTaskListResponse"];
export type OpsVideoTask = components["schemas"]["OpsVideoTaskResponse"];
export type TranscriptContent = components["schemas"]["TranscriptResponse"];
export type TranscriptCueList = components["schemas"]["TranscriptCueListResponse"];
export type TranscriptCue = components["schemas"]["TranscriptCueResponse"];
export type MicroEventExtractRequest =
  components["schemas"]["MicroEventExtractRequest"];
export type MicroEventExtractResult =
  components["schemas"]["MicroEventExtractResponse"];
export type MicroEventBatchExtractRequest =
  components["schemas"]["MicroEventBatchExtractRequest"];
export type MicroEventBatchExtractResult =
  components["schemas"]["MicroEventBatchExtractResponse"];
export type MicroEventExtractionDetail =
  components["schemas"]["MicroEventExtractionDetailResponse"];
export type MicroEventExtractionWindow =
  components["schemas"]["MicroEventExtractionWindowResponse"];
export type MicroEventCandidate =
  components["schemas"]["MicroEventCandidateResponse"];
export type AsrCorrectionCandidate =
  components["schemas"]["AsrCorrectionCandidateResponse"];
export type OperationEventList = components["schemas"]["OperationEventListResponse"];
export type OperationEvent = components["schemas"]["OperationEventResponse"];
export type CodexUsageList = components["schemas"]["CodexUsageListResponse"];
export type CodexUsage = components["schemas"]["CodexUsageResponse"];
export type CodexUsageByVideoList =
  components["schemas"]["CodexUsageByVideoResponse"];
export type CodexUsageVideoSummary =
  components["schemas"]["CodexUsageVideoSummaryResponse"];
export type CodexUsageByJobList =
  components["schemas"]["CodexUsageByJobResponse"];
export type CodexUsageJobSummary =
  components["schemas"]["CodexUsageJobSummaryResponse"];
export type DomainEntryType = components["schemas"]["DomainEntryTypeResponse"];
export type DomainEntryTypeCreateRequest =
  components["schemas"]["DomainEntryTypeCreateRequest"];
export type DomainEntryList = components["schemas"]["DomainEntryListResponse"];
export type DomainEntry = components["schemas"]["DomainEntryResponse"];
export type DomainEntryCreateRequest =
  components["schemas"]["DomainEntryCreateRequest"];
export type DomainEntryUpdateRequest =
  components["schemas"]["DomainEntryUpdateRequest"];
export type DomainEntryAliasCreateRequest =
  components["schemas"]["DomainEntryAliasCreateRequest"];
export type DomainEntryAliasUpdateRequest =
  components["schemas"]["DomainEntryAliasUpdateRequest"];
export type DomainEntryStreamerLinkRequest =
  components["schemas"]["DomainEntryStreamerLinkRequest"];
export type OpsSchemaGraph = components["schemas"]["OpsSchemaGraphResponse"];
export type OpsSchemaTable = components["schemas"]["OpsSchemaTableResponse"];
export type Streamer = components["schemas"]["StreamerResponse"];
export type PipelineJobList = components["schemas"]["ListPipelineJobsResponse"];
export type PipelineJobSummary = components["schemas"]["PipelineJobSummaryResponse"];
export type CollectChannelVideosResult =
  components["schemas"]["CollectChannelVideosResponse"];
export type CollectAllTranscriptsResult =
  components["schemas"]["CollectAllTranscriptTasksResponse"];
export type CollectChannelTranscriptsResult =
  components["schemas"]["CollectChannelTranscriptTasksResponse"];
export type GenerateAllTranscriptCuesResult =
  components["schemas"]["GenerateAllTranscriptCueTasksResponse"];
export type GenerateChannelTranscriptCuesResult =
  components["schemas"]["GenerateChannelTranscriptCueTasksResponse"];
export type ResolveYouTubeChannelResult =
  components["schemas"]["ResolveYouTubeChannelResponse"];
export type RetryPipelineJobResult = components["schemas"]["RetryPipelineJobResponse"];
export type PipelineJobStatusFilter = NonNullable<
  NonNullable<paths["/pipeline/jobs"]["get"]["parameters"]["query"]>["status"]
>;
export type PipelineJobFilters = NonNullable<
  paths["/pipeline/jobs"]["get"]["parameters"]["query"]
>;
export type OpsVideoFilters = NonNullable<
  paths["/ops/videos"]["get"]["parameters"]["query"]
>;
export type OpsVideoTaskFilters = NonNullable<
  paths["/ops/video-tasks"]["get"]["parameters"]["query"]
>;
export type OperationEventFilters = NonNullable<
  NonNullable<paths["/ops/events"]["get"]["parameters"]["query"]>
>;
export type CodexUsageFilters = NonNullable<
  NonNullable<paths["/ops/codex-usage"]["get"]["parameters"]["query"]>
>;
export type CodexUsageByVideoFilters = NonNullable<
  NonNullable<paths["/ops/codex-usage/by-video"]["get"]["parameters"]["query"]>
>;
export type CodexUsageByJobFilters = NonNullable<
  NonNullable<paths["/ops/codex-usage/by-job"]["get"]["parameters"]["query"]>
>;
export type DomainEntryFilters = NonNullable<
  NonNullable<paths["/domain-entries"]["get"]["parameters"]["query"]>
>;
