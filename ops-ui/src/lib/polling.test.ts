import { adaptiveRefetchInterval } from "@/lib/polling";
import { expect, it } from "vitest";

it("실행 중이면 5초, 안정 상태면 15초로 polling한다", () => {
  expect(adaptiveRefetchInterval([{ status: "running" }])).toBe(5_000);
  expect(adaptiveRefetchInterval([{ status: "succeeded" }])).toBe(15_000);
});

it("숨겨진 탭에서는 polling을 중지한다", () => {
  Object.defineProperty(document, "visibilityState", { value: "hidden", configurable: true });
  expect(adaptiveRefetchInterval([{ status: "running" }])).toBe(false);
  Object.defineProperty(document, "visibilityState", { value: "visible", configurable: true });
});
