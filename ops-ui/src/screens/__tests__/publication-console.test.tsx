import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { expect, it, vi } from "vitest";

import type { ArchiveCurrent, ArchiveVideos, PublicationStatusList } from "@/features/publishing/api";
import { PublishingConsole } from "@/screens/publishing-console";
import { server } from "@/test/server";

const replace = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push: vi.fn() }), usePathname: () => "/publishing", useSearchParams: () => new URLSearchParams() }));

const emptyArchiveVideos = { items: [], limit: 50, offset: 0, total: 0 } as ArchiveVideos;
const archiveCurrent = { environment: "prod", publishMode: "prod", latestPublication: null, storage: { configured: false, bucket: null } } as ArchiveCurrent;
const publicationStatuses = { limit: 50, offset: 0, total: 1, items: [{ id: 44, profileId: 7, profileKey: "archive-prod", profileName: "Archive production", profileRevisionId: 9, routeId: 12, publishMode: "prod", environment: "prod", schemaVersion: 1, version: "v1", status: "failed", videoCount: 2, artifactCount: 2, createdAt: "2026-07-18T00:00:00Z", updatedAt: "2026-07-18T00:01:00Z", errorCode: "publication.delivery_failed", errorMessage: "One required delivery failed.", deliveries: [{ id: 3, destinationId: 4, destinationKey: "public-archive", destinationName: "Public Archive", objectBindingId: 5, required: true, status: "failed", indexPublicUrl: "https://example.test/index.json", pointerPublicUrl: "https://example.test/pointer.json", errorCode: "storage.write_failed", errorMessage: "Object storage refused the write.", updatedAt: "2026-07-18T00:01:00Z" }] }] } as PublicationStatusList;

function renderWithQuery(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}

it("keeps the stage form input mounted, focused, and selected while archive data refreshes", async () => {
  server.use(
    http.get("/ops/api/backend/ops/archive/current", async () => { await delay(30); return HttpResponse.json(archiveCurrent); }),
    http.get("/ops/api/backend/ops/archive/videos", async () => { await delay(30); return HttpResponse.json(emptyArchiveVideos); }),
  );
  const { client } = renderWithQuery(<PublishingConsole initialCurrent={archiveCurrent} initialVideos={emptyArchiveVideos} />);
  const input = screen.getByRole("textbox", { name: "Video IDs" }) as HTMLInputElement;
  fireEvent.change(input, { target: { value: "12, 34" } });
  input.focus(); input.setSelectionRange(1, 4);
  await client.invalidateQueries({ queryKey: ["publishing"] });
  await waitFor(() => expect(client.isFetching()).toBe(0));
  expect(screen.getByRole("textbox", { name: "Video IDs" })).toBe(input);
  expect(document.activeElement).toBe(input);
  expect(input.selectionStart).toBe(1); expect(input.selectionEnd).toBe(4);
});

it("posts video IDs to the artifact-build stage and renders the returned status", async () => {
  const captured: { body: Record<string, unknown> | null } = { body: null };
  server.use(http.post("/ops/api/backend/ops/operations/archive-artifact-build", async ({ request }) => { captured.body = await request.json() as Record<string, unknown>; return HttpResponse.json({ stage: "artifactBuild", status: "succeeded", artifactIds: [101, 102], profileRevisionId: null, routeId: null, publicationId: null, destinationResults: [], missingPreconditions: [], metadata: {} }); }));
  renderWithQuery(<PublishingConsole initialCurrent={archiveCurrent} initialVideos={emptyArchiveVideos} />);
  fireEvent.change(screen.getByRole("textbox", { name: "Video IDs" }), { target: { value: "12, 34" } });
  fireEvent.click(screen.getByRole("button", { name: "Run Build artifacts" }));
  await waitFor(() => expect(captured.body).toEqual({ videoIds: [12, 34], publishMode: "prod", environment: "prod", variant: "control", schemaVersion: 1, retryFailed: true, rerunSucceeded: false, includeNonEmbeddable: false }));
  expect(await screen.findByText("Latest result: Build artifacts")).toBeTruthy();
  expect(screen.getAllByText("succeeded")).toHaveLength(1);
});

it("shows persisted publication and destination delivery errors", async () => {
  server.use(http.get("/ops/api/backend/ops/publish/publications", () => HttpResponse.json(publicationStatuses)));
  renderWithQuery(<PublishingConsole initialCurrent={archiveCurrent} initialVideos={emptyArchiveVideos} initialPublications={publicationStatuses} />);
  expect(await screen.findByText((_, element) => element?.textContent?.includes("Archive production") ?? false, { selector: "p" })).toBeTruthy();
  expect(screen.getByText("Public Archive")).toBeTruthy();
  expect(screen.getByText(/storage.write_failed/)).toBeTruthy();
});

it("requires dialog confirmation before publishing a production pointer", async () => {
  const requests: Record<string, unknown>[] = [];
  server.use(http.post("/ops/api/backend/ops/operations/archive-pointer-publish", async ({ request }) => { requests.push(await request.json() as Record<string, unknown>); return HttpResponse.json({ stage: "pointerPublish", status: "succeeded", artifactIds: [], profileRevisionId: null, routeId: null, publicationId: 88, destinationResults: [], missingPreconditions: [], metadata: {} }); }));
  renderWithQuery(<PublishingConsole initialCurrent={archiveCurrent} initialVideos={emptyArchiveVideos} />);
  fireEvent.change(screen.getByRole("combobox", { name: "Stage" }), { target: { value: "pointerPublish" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Artifact IDs" }), { target: { value: "101, 102" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "Profile revision ID" }), { target: { value: "9" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "Publication ID" }), { target: { value: "88" } });
  const reviewButton = screen.getByRole("button", { name: "Review production pointer" });
  fireEvent.submit(reviewButton.closest("form")!);
  expect(requests).toHaveLength(0);
  expect(screen.getByRole("alert").textContent).toContain("confirmation dialog");
  fireEvent.click(reviewButton);
  const dialog = await screen.findByRole("dialog");
  const confirmation = dialog.querySelector<HTMLInputElement>('input[name="confirmation"]');
  expect(confirmation).not.toBeNull();
  fireEvent.change(confirmation!, { target: { value: "88" } });
  fireEvent.click(screen.getByRole("button", { name: "Publish production pointer" }));
  await waitFor(() => expect(requests).toEqual([{ publicationId: 88, artifactIds: [101, 102], profileRevisionId: 9, publishMode: "prod", environment: "prod" }]));
  await waitFor(() => expect(document.activeElement).toBe(reviewButton));
});

it("shows missing predecessor details returned by a stage 409", async () => {
  server.use(http.post("/ops/api/backend/ops/operations/archive-object-deliver", () => HttpResponse.json({ error: { code: "publication.stage_precondition_failed", message: "Publication stage is missing required predecessor state.", details: { stage: "objectDeliver", missingPreconditions: [{ kind: "canonicalArtifact", artifactId: 101, status: "pending" }] } } }, { status: 409 })));
  renderWithQuery(<PublishingConsole initialCurrent={archiveCurrent} initialVideos={emptyArchiveVideos} />);
  fireEvent.change(screen.getByRole("combobox", { name: "Stage" }), { target: { value: "objectDeliver" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Artifact IDs" }), { target: { value: "101" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "Profile revision ID" }), { target: { value: "7" } });
  fireEvent.click(screen.getByRole("button", { name: "Run Deliver objects" }));
  const preconditionError = await screen.findByText(/canonicalArtifact/, { selector: "p" });
  expect(preconditionError.textContent).toContain("canonicalArtifact");
  expect(preconditionError.textContent).toContain("artifactId");
});
