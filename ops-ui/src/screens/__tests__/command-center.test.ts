import { describe, expect, it } from "vitest";

import { summarizeQueues } from "@/screens/command-center";

describe("summarizeQueues", () => {
  it("groups status rows into one queue row per task type", () => {
    expect(
      summarizeQueues([
        { taskType: "timeline_compose", status: "pending", count: 2 },
        { taskType: "timeline_compose", status: "running", count: 1 },
        { taskType: "timeline_compose", status: "failed", count: 3 },
        { taskType: "timeline_compose", status: "succeeded", count: 20 },
      ]),
    ).toEqual([
      { taskType: "timeline_compose", pending: 2, running: 1, failed: 3 },
    ]);
  });
});
