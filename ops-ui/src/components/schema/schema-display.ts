export type SchemaTableGroup = "core" | "processing" | "artifacts" | "support";

export function getTableGroup(tableName: string): SchemaTableGroup {
  if (["streamers", "channels", "videos"].includes(tableName)) {
    return "core";
  }
  if (["pipeline_jobs", "pipeline_job_attempts", "video_tasks"].includes(tableName)) {
    return "processing";
  }
  if (["external_api_calls", "youtube_transcripts"].includes(tableName)) {
    return "artifacts";
  }
  return "support";
}
