import { describe, expect, it } from "vitest";
import {
  estimateTableNodeHeight,
  getRelationCardinality,
  getTableGroup,
} from "./schema-display";

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

describe("estimateTableNodeHeight", () => {
  it("does not cap tables with more than ten columns", () => {
    const height = estimateTableNodeHeight({
      columns: Array.from({ length: 16 }, () => ({})),
    });

    expect(height).toBeGreaterThan(420);
  });

  it("accounts for default rows that render with an extra line", () => {
    const compactHeight = estimateTableNodeHeight({ columns: [{}, {}, {}, {}] });
    const defaultHeight = estimateTableNodeHeight({
      columns: [{ default: "now()" }, {}, {}, {}],
    });

    expect(defaultHeight).toBeGreaterThan(compactHeight);
  });
});
