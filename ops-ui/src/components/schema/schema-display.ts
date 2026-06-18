export type SchemaTableGroup = "core" | "processing" | "artifacts" | "support";
export type SchemaRelationKind =
  | "one_to_many"
  | "one_to_one"
  | "optional_one_to_many"
  | "optional_one_to_one";

export type RelationCardinality = {
  parentLabel: "1";
  childLabel: "0..*" | "1..*" | "0..1" | "1";
  childIsMany: boolean;
  childIsOptional: boolean;
};

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

export function getRelationCardinality(
  relationKind: SchemaRelationKind,
): RelationCardinality {
  const childIsOptional = relationKind.startsWith("optional_");
  const childIsMany = relationKind.endsWith("_many");
  if (childIsMany) {
    return {
      parentLabel: "1",
      childLabel: childIsOptional ? "0..*" : "1..*",
      childIsMany,
      childIsOptional,
    };
  }
  return {
    parentLabel: "1",
    childLabel: childIsOptional ? "0..1" : "1",
    childIsMany,
    childIsOptional,
  };
}
