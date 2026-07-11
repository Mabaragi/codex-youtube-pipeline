import type { components, paths } from "@/generated/codex-api";

type Schemas = components["schemas"];

export type OpsSummary = Schemas["OpsSummaryResponse"];
export type OpsChannelList = Schemas["OpsChannelListResponse"];
export type OpsChannel = Schemas["OpsChannelResponse"];
export type OpsVideoList = Schemas["OpsVideoListResponse"];
export type OpsVideo = Schemas["OpsVideoResponse"];
export type OpsVideoDetail = Schemas["OpsVideoDetailResponse"];
export type OpsVideoTask = Schemas["OpsVideoTaskResponse"];
export type OpsRefreshVideoEmbedStatusRequest =
  Schemas["OpsRefreshVideoEmbedStatusRequest"];
export type OpsRefreshVideoEmbedStatusResponse =
  Schemas["OpsRefreshVideoEmbedStatusResponse"];

export type WorkItem = Schemas["WorkItemResponse"];
export type WorkItemDetail = Schemas["WorkItemDetailResponse"];
export type WorkItemList = Schemas["WorkItemListResponse"];
export type WorkBatchDetail = Schemas["WorkBatchDetailResponse"];
export type WorkflowRunDetail = Schemas["WorkflowRunDetailResponse"];
export type WorkItemStatus = Schemas["WorkItemStatus"];
export type WorkItemFilters = NonNullable<
  paths["/ops/work-items"]["get"]["parameters"]["query"]
>;

export type VideoSelection =
  | Schemas["SelectedVideoSelectionRequest"]
  | Schemas["ChannelVideoSelectionRequest"]
  | Schemas["FilterVideoSelectionRequest"]
  | Schemas["NextEligibleVideoSelectionRequest"];
export type OperationBatchResult = Schemas["OperationBatchResponse"];
export type ChannelOperationBatchResult = Schemas["ChannelOperationBatchResponse"];
export type ChannelResolveOperationResult =
  Schemas["ChannelResolveOperationResponse"];
export type WorkflowBatchResult = Schemas["WorkflowBatchResponse"];
export type TranscriptCollectOperationRequest =
  Schemas["TranscriptCollectOperationRequest"];
export type TranscriptCueOperationRequest =
  Schemas["TranscriptCueOperationRequest"];
export type MicroEventOperationRequest = Schemas["MicroEventOperationRequest"];
export type TimelineOperationRequest = Schemas["TimelineOperationRequest"];
export type ArchivePublishOperationRequest =
  Schemas["ArchivePublishOperationRequest"];
export type VideoCollectOperationRequest =
  Schemas["VideoCollectOperationRequest"];
export type ChannelResolveOperationRequest =
  Schemas["ChannelResolveOperationRequest"];
export type ProcessToPublishOperationRequest =
  Schemas["ProcessToPublishOperationRequest"];

export type TranscriptContent = Schemas["TranscriptResponse"];
export type TranscriptCueList = Schemas["TranscriptCueListResponse"];
export type TranscriptCue = Schemas["TranscriptCueResponse"];
export type MicroEventExtractionDetail =
  Schemas["MicroEventExtractionDetailResponse"];
export type MicroEventExtractionWindow =
  Schemas["MicroEventExtractionWindowResponse"];
export type MicroEventCandidate = Schemas["MicroEventCandidateResponse"];
export type AsrCorrectionCandidate = Schemas["AsrCorrectionCandidateResponse"];
export type TimelineComposition = Schemas["TimelineCompositionResponse"];
export type TimelineEpisode = Schemas["TimelineEpisodeResponse"];
export type TimelineBlock = Schemas["TimelineBlockResponse"];

export type ArchiveCurrent = Schemas["ArchiveCurrentResponse"];
export type ArchiveOpsVideoList = Schemas["ArchiveOpsVideoListResponse"];
export type ArchiveOpsVideo = Schemas["ArchiveOpsVideoResponse"];

export type OperationEventList = Schemas["OperationEventListResponse"];
export type OperationEvent = Schemas["OperationEventResponse"];
export type CodexUsageList = Schemas["CodexUsageListResponse"];
export type CodexUsage = Schemas["CodexUsageResponse"];
export type CodexUsageByVideoList = Schemas["CodexUsageByVideoResponse"];
export type CodexUsageVideoSummary =
  Schemas["CodexUsageVideoSummaryResponse"];
export type CodexUsageByJobList = Schemas["CodexUsageByJobResponse"];
export type CodexUsageJobSummary = Schemas["CodexUsageJobSummaryResponse"];

export type DomainEntryType = Schemas["DomainEntryTypeResponse"];
export type DomainEntryTypeCreateRequest =
  Schemas["DomainEntryTypeCreateRequest"];
export type DomainEntryList = Schemas["DomainEntryListResponse"];
export type DomainEntry = Schemas["DomainEntryResponse"];
export type DomainEntryCreateRequest = Schemas["DomainEntryCreateRequest"];
export type DomainEntryUpdateRequest = Schemas["DomainEntryUpdateRequest"];
export type DomainEntryAliasCreateRequest =
  Schemas["DomainEntryAliasCreateRequest"];
export type DomainEntryAliasUpdateRequest =
  Schemas["DomainEntryAliasUpdateRequest"];
export type DomainEntryStreamerLinkRequest =
  Schemas["DomainEntryStreamerLinkRequest"];

export type PromptBody = Schemas["PromptBodyResponse"];
export type PromptSummary = Schemas["PromptSummaryResponse"];
export type PromptDetail = Schemas["PromptDetailResponse"];
export type PromptVersion = Schemas["PromptVersionResponse"];
export type PromptVersionCreateRequest = Schemas["PromptVersionCreateRequest"];
export type PromptVersionUpdateRequest = Schemas["PromptVersionUpdateRequest"];
export type PromptCacheInvalidateRequest =
  Schemas["PromptCacheInvalidateRequest"];
export type PromptCacheInvalidateResponse =
  Schemas["PromptCacheInvalidateResponse"];
export type PromptKey = PromptSummary["key"];

export type OpsSchemaGraph = Schemas["OpsSchemaGraphResponse"];
export type OpsSchemaTable = Schemas["OpsSchemaTableResponse"];
export type Streamer = Schemas["StreamerResponse"];

export type OpsVideoFilters = NonNullable<
  paths["/ops/videos"]["get"]["parameters"]["query"]
>;
export type ArchiveOpsVideoFilters = NonNullable<
  paths["/ops/archive/videos"]["get"]["parameters"]["query"]
>;
export type OperationEventFilters = NonNullable<
  paths["/ops/events"]["get"]["parameters"]["query"]
>;
export type CodexUsageFilters = NonNullable<
  paths["/ops/codex-usage"]["get"]["parameters"]["query"]
>;
export type CodexUsageByVideoFilters = NonNullable<
  paths["/ops/codex-usage/by-video"]["get"]["parameters"]["query"]
>;
export type CodexUsageByJobFilters = NonNullable<
  paths["/ops/codex-usage/by-job"]["get"]["parameters"]["query"]
>;
export type DomainEntryFilters = NonNullable<
  paths["/ops/domain-entries"]["get"]["parameters"]["query"]
>;
