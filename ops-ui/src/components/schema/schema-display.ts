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

type TableHeightColumn = {
  default?: string | null;
};

type TableHeightTable = {
  columns: TableHeightColumn[];
};

const TABLE_HEADER_HEIGHT = 58;
const TABLE_MIN_HEIGHT = 148;
const TABLE_ROW_HEIGHT = 44;
const TABLE_ROW_WITH_DEFAULT_HEIGHT = 60;

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

export function estimateTableNodeHeight(table: TableHeightTable): number {
  const columnsHeight = table.columns.reduce(
    (height, column) =>
      height + (column.default ? TABLE_ROW_WITH_DEFAULT_HEIGHT : TABLE_ROW_HEIGHT),
    0,
  );
  return Math.max(TABLE_MIN_HEIGHT, TABLE_HEADER_HEIGHT + columnsHeight);
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
