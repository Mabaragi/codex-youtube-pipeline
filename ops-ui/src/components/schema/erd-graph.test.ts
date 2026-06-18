import { describe, expect, it } from "vitest";
import { getRelationCardinality, getTableGroup } from "./schema-display";

describe("getTableGroup", () => {
  it("groups known operational tables", () => {
    expect(getTableGroup("channels")).toBe("core");
    expect(getTableGroup("video_tasks")).toBe("processing");
    expect(getTableGroup("external_api_calls")).toBe("artifacts");
    expect(getTableGroup("unknown_table")).toBe("support");
  });
});

describe("getRelationCardinality", () => {
  it("maps relation kinds to ERD cardinality labels", () => {
    expect(getRelationCardinality("one_to_many")).toMatchObject({
      parentLabel: "1",
      childLabel: "1..*",
      childIsMany: true,
      childIsOptional: false,
    });
    expect(getRelationCardinality("optional_one_to_one")).toMatchObject({
      parentLabel: "1",
      childLabel: "0..1",
      childIsMany: false,
      childIsOptional: true,
    });
  });
});
