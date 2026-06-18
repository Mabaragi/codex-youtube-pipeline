import type { components, paths } from "@/generated/codex-api";

export type OpsSummary = components["schemas"]["OpsSummaryResponse"];
export type OpsChannelList = components["schemas"]["OpsChannelListResponse"];
export type OpsChannel = components["schemas"]["OpsChannelResponse"];
export type OpsVideoList = components["schemas"]["OpsVideoListResponse"];
export type OpsVideo = components["schemas"]["OpsVideoResponse"];
export type OpsVideoTaskList = components["schemas"]["OpsVideoTaskListResponse"];
export type OpsVideoTask = components["schemas"]["OpsVideoTaskResponse"];
export type OpsSchemaGraph = components["schemas"]["OpsSchemaGraphResponse"];
export type OpsSchemaTable = components["schemas"]["OpsSchemaTableResponse"];
export type PipelineJobList = components["schemas"]["ListPipelineJobsResponse"];
export type PipelineJobSummary = components["schemas"]["PipelineJobSummaryResponse"];
export type CollectChannelVideosResult =
  components["schemas"]["CollectChannelVideosResponse"];
export type CollectChannelTranscriptsResult =
  components["schemas"]["CollectChannelTranscriptTasksResponse"];
export type RetryPipelineJobResult = components["schemas"]["RetryPipelineJobResponse"];
export type PipelineJobStatusFilter = NonNullable<
  NonNullable<paths["/pipeline/jobs"]["get"]["parameters"]["query"]>["status"]
>;
