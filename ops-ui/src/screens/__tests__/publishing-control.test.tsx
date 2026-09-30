import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { expect, it } from "vitest";

import { PublishingControl } from "@/features/automation/publishing-control";
import { server } from "@/test/server";

function renderControl() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><PublishingControl /></QueryClientProvider>);
  return client;
}

it("OFF에서 사유를 입력하고 확인한 뒤 ON으로 바꾸며 같은 버튼에 focus를 복원한다", async () => {
  let enabled = false;
  const requests: unknown[] = [];
  const publishing = () => ({ enabled, pendingCount: 3, runningCount: 0, updatedAt: null, reason: null });
  server.use(
    http.get("/ops/api/backend/ops/automation/status", () => HttpResponse.json({ runtime: { state: "active" }, publishing: publishing() })),
    http.put("/ops/api/backend/ops/automation/publishing", async ({ request }) => {
      requests.push(await request.json());
      await delay(30); enabled = true;
      return HttpResponse.json(publishing());
    }),
  );
  const client = renderControl();
  await screen.findByText("게시 OFF · 대기 3 · 실행 0");
  const trigger = screen.getByRole("button", { name: "게시 설정" });
  trigger.focus(); fireEvent.click(trigger);
  const reason = screen.getByRole("textbox", { name: /작업 사유/ });
  fireEvent.change(reason, { target: { value: "대기 작업 게시 재개" } }); reason.focus();
  await client.invalidateQueries({ queryKey: ["automation"] });
  expect(screen.getByRole("textbox", { name: /작업 사유/ })).toBe(reason);
  expect(document.activeElement).toBe(reason);
  fireEvent.click(screen.getByRole("button", { name: "게시 켜기" }));
  await screen.findByText("게시 ON · 대기 3 · 실행 0");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(requests).toEqual([{ enabled: true, reason: "대기 작업 게시 재개" }]);
  expect(screen.getByRole("button", { name: "게시 설정" })).toBe(trigger);
  await waitFor(() => expect(document.activeElement).toBe(trigger));
});

it("전환 실패를 dialog 안에 표시하고 사유 입력과 기존 OFF 상태를 보존한다", async () => {
  server.use(
    http.get("/ops/api/backend/ops/automation/status", () => HttpResponse.json({ runtime: { state: "active" }, publishing: { enabled: false, pendingCount: 0, runningCount: 0, updatedAt: null, reason: null } })),
    http.put("/ops/api/backend/ops/automation/publishing", () => HttpResponse.json({ error: { code: "test.failure", message: "설정 저장 실패" } }, { status: 500 })),
  );
  renderControl();
  await screen.findByText("게시 OFF · 대기 0 · 실행 0");
  fireEvent.click(screen.getByRole("button", { name: "게시 설정" }));
  const reason = screen.getByRole("textbox", { name: /작업 사유/ }) as HTMLTextAreaElement;
  fireEvent.change(reason, { target: { value: "재개 검증" } });
  fireEvent.click(screen.getByRole("button", { name: "게시 켜기" }));
  expect((await screen.findByRole("alert")).textContent).toContain("설정 저장 실패");
  expect(reason.value).toBe("재개 검증");
  expect(screen.getByRole("textbox", { name: /작업 사유/ })).toBe(reason);
  expect(screen.getByText("게시 OFF · 대기 0 · 실행 0")).toBeTruthy();
});
