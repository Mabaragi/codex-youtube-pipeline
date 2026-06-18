import { describe, expect, it } from "vitest";
import { getTableGroup } from "./schema-display";

describe("getTableGroup", () => {
  it("groups known operational tables", () => {
    expect(getTableGroup("channels")).toBe("core");
    expect(getTableGroup("video_tasks")).toBe("processing");
    expect(getTableGroup("external_api_calls")).toBe("artifacts");
    expect(getTableGroup("unknown_table")).toBe("support");
  });
});
