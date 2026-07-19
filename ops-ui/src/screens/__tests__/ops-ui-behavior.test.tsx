import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { expect, it, vi } from "vitest";

import type { Incident } from "@/features/automation/api";
import type { VideoList } from "@/features/content/api";
import { IncidentDetail } from "@/screens/incident-detail";
import { OperationsConsole } from "@/screens/operations-console";
import { VideosConsole } from "@/screens/videos-console";
import { server } from "@/test/server";
import { BFF_BASE_URL } from "@/lib/api";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }), usePathname: () => "/content/videos", useSearchParams: () => new URLSearchParams() }));

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}

const emptyVideos = { items: [], limit: 50, offset: 0, total: 0 } as VideoList;

it("테스트 BFF origin을 동일 출처 절대 URL로 구성한다", () => {
  expect(BFF_BASE_URL).toBe("http://localhost:3000/ops/api/backend");
});

it("background refetch 중에도 검색 input identity, focus, selection을 보존한다", async () => {
  server.use(http.get("/ops/api/backend/ops/videos", async () => { await delay(30); return HttpResponse.json(emptyVideos); }));
  const { client } = renderWithQuery(<VideosConsole initialData={emptyVideos} />);
  const input = screen.getByRole("textbox", { name: "검색" }) as HTMLInputElement;
  fireEvent.change(input, { target: { value: "테스트 영상" } });
  input.focus(); input.setSelectionRange(2, 4);
  await client.invalidateQueries({ queryKey: ["videos"] });
  await waitFor(() => expect(client.isFetching()).toBe(0));
  expect(screen.getByRole("textbox", { name: "검색" })).toBe(input);
  expect(document.activeElement).toBe(input);
  expect(input.selectionStart).toBe(2); expect(input.selectionEnd).toBe(4);
});

it("오류 envelope를 목록의 접근 가능한 error 상태로 표시한다", async () => {
  let hit = 0;
  server.use(http.get("http://localhost:3000/ops/api/backend/ops/videos", () => { hit += 1; return HttpResponse.json({ error: { code: "pipeline.test_failure", message: "의도한 테스트 오류" } }, { status: 500 }); }));
  renderWithQuery(<VideosConsole initialData={null} />);
  await waitFor(() => expect(hit).toBe(1));
  expect((await screen.findByRole("alert")).textContent).toContain("pipeline.test_failure");
});

it("전체 pipeline 확인 후 Sol medium 운영 계약을 BFF로 전송한다", async () => {
  const captured: { body: Record<string, unknown> | null } = { body: null };
  server.use(http.post("/ops/api/backend/ops/workflows/process-to-publish", async ({ request }) => { captured.body = await request.json() as Record<string, unknown>; return HttpResponse.json({ batchId: 1, createdCount: 1, requestedCount: 1, reusedCount: 0, skippedCount: 0, items: [] }); }));
  renderWithQuery(<OperationsConsole />);
  fireEvent.click(screen.getByRole("button", { name: "전체 실행" }));
  fireEvent.click(screen.getByRole("button", { name: "Workflow 생성" }));
  await waitFor(() => expect(captured.body).not.toBeNull());
  expect(captured.body).toMatchObject({ microModel: "gpt-5.6-sol", microReasoningEffort: "high", timelineModel: "gpt-5.6-luna", timelineReasoningEffort: "xhigh", publishMode: "prod" });
});

it("incident 안전 조치에 한 번 생성한 idempotency key를 포함한다", async () => {
  const captured: { body: Record<string, unknown> | null } = { body: null };
  const incident = { id: 7, incidentType: "transient", severity: "warning", state: "open", fingerprint: "fp", firstSeenAt: "2026-07-14T00:00:00Z", lastSeenAt: "2026-07-14T00:00:00Z", occurrenceCount: 1, resolvedAt: null, errorType: "CodexConnectionClosed", errorMessage: "closed", taskType: "micro_event_extract", workItemId: 10, workflowRunId: 2, metadata: {} } as Incident;
  server.use(http.get("/ops/api/backend/ops/incidents/7", () => HttpResponse.json(incident)), http.post("/ops/api/backend/ops/incidents/7/actions", async ({ request }) => { captured.body = await request.json() as Record<string, unknown>; return HttpResponse.json({ action: "retry", incidentId: 7, result: {} }); }));
  renderWithQuery(<IncidentDetail id={7} initialData={incident} />);
  fireEvent.click(screen.getByRole("button", { name: "동일 입력 재시도" }));
  fireEvent.click(screen.getByRole("button", { name: "실행" }));
  await waitFor(() => expect(captured.body).not.toBeNull());
  expect(captured.body?.action).toBe("retry");
  expect(String(captured.body?.idempotencyKey)).toMatch(/^[0-9a-f-]{36}$/);
});

it("timeout 연장 조치에 30분 증분을 전송한다", async () => {
  const captured: { body: Record<string, unknown> | null } = { body: null };
  const incident = { id: 8, incidentType: "transient", severity: "warning", state: "open", fingerprint: "fp-timeout", firstSeenAt: "2026-07-14T00:00:00Z", lastSeenAt: "2026-07-14T00:00:00Z", occurrenceCount: 1, resolvedAt: null, errorType: "TimeoutError", errorMessage: "timed out", taskType: "micro_event_extract", workItemId: 11, workflowRunId: 3, metadata: {} } as Incident;
  server.use(http.get("/ops/api/backend/ops/incidents/8", () => HttpResponse.json(incident)), http.post("/ops/api/backend/ops/incidents/8/actions", async ({ request }) => { captured.body = await request.json() as Record<string, unknown>; return HttpResponse.json({ action: "extend_timeout", incidentId: 8, result: { timeoutSeconds: 5400 } }); }));
  renderWithQuery(<IncidentDetail id={8} initialData={incident} />);
  fireEvent.click(screen.getByRole("button", { name: "30분 연장" }));
  fireEvent.click(screen.getByRole("button", { name: "실행" }));
  await waitFor(() => expect(captured.body).not.toBeNull());
  expect(captured.body).toMatchObject({ action: "extend_timeout", parameters: { extensionSeconds: 1800 } });
});

it("work item이 없는 incident에는 대상 필수 조치를 노출하지 않는다", () => {
  const incident = { id: 9, incidentType: "data_integrity", severity: "error", state: "open", fingerprint: "fp-orphan", firstSeenAt: "2026-07-14T00:00:00Z", lastSeenAt: "2026-07-14T00:00:00Z", occurrenceCount: 1, resolvedAt: null, errorType: "OrphanVideoChannelMissing", errorMessage: "orphan", taskType: null, workItemId: null, workflowRunId: null, metadata: {} } as Incident;
  server.use(http.get("/ops/api/backend/ops/incidents/9", () => HttpResponse.json(incident)));
  renderWithQuery(<IncidentDetail id={9} initialData={incident} />);
  expect(screen.queryByRole("button", { name: "동일 입력 재시도" })).toBeNull();
  expect(screen.queryByRole("button", { name: "30분 연장" })).toBeNull();
  expect(screen.getByRole("button", { name: "만료 lease 복구" }).hasAttribute("disabled")).toBe(false);
});
