import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { expect, it } from "vitest";

import type { ChannelList, Streamer } from "@/features/catalog/api";
import { ChannelsConsole } from "@/screens/channels-console";
import { server } from "@/test/server";

const channels = { items: [] } as ChannelList;
const streamers = [
  { id: 1, name: "Existing Streamer", publishProfileId: 7 },
] as Streamer[];

function renderConsole() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <ChannelsConsole initialChannels={channels} initialStreamers={streamers} />
    </QueryClientProvider>,
  );
}

it("sends an operator reason when creating and updating streamers", async () => {
  const createRequests: Array<{ body: unknown; reason: string | null }> = [];
  const updateRequests: Array<{ body: unknown; reason: string | null }> = [];
  server.use(
    http.get("/ops/api/backend/ops/channels", () => HttpResponse.json(channels)),
    http.get("/ops/api/backend/ops/streamers", () => HttpResponse.json(streamers)),
    http.get("/ops/api/backend/ops/publish/profiles", () =>
      HttpResponse.json([
        {
          id: 7,
          key: "archive-prod",
          name: "Archive Production",
          description: null,
          activeRevisionId: 9,
          createdAt: "2026-07-18T00:00:00Z",
        },
      ]),
    ),
    http.post("/ops/api/backend/ops/streamers", async ({ request }) => {
      createRequests.push({
        body: await request.json(),
        reason: request.headers.get("X-Operator-Reason"),
      });
      return HttpResponse.json(
        { id: 2, name: "New Streamer", publishProfileId: 7 },
        { status: 201 },
      );
    }),
    http.patch("/ops/api/backend/ops/streamers/1", async ({ request }) => {
      updateRequests.push({
        body: await request.json(),
        reason: request.headers.get("X-Operator-Reason"),
      });
      return HttpResponse.json({ id: 1, name: "Renamed Streamer", publishProfileId: 7 });
    }),
  );

  renderConsole();
  const addButton = screen.getByRole("button", { name: "Add Streamer" });
  const createForm = addButton.closest("form");
  expect(createForm).not.toBeNull();
  const createControls = within(createForm!);
  fireEvent.change(createControls.getByRole("textbox", { name: "Streamer name" }), {
    target: { value: "New Streamer" },
  });
  const profile = await createControls.findByRole("combobox", {
    name: "Publication profile",
  });
  await waitFor(() => expect(profile.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(profile, { target: { value: "7" } });
  fireEvent.change(createControls.getByRole("textbox", { name: "Operator reason" }), {
    target: { value: "Assign the initial publication route" },
  });
  fireEvent.click(addButton);

  await waitFor(() => expect(createRequests).toHaveLength(1));
  expect(createRequests[0]).toEqual({
    body: { name: "New Streamer", publishProfileId: 7 },
    reason: "Assign%20the%20initial%20publication%20route",
  });

  const saveButton = screen.getByRole("button", { name: "Save" });
  const updateForm = saveButton.closest("form");
  expect(updateForm).not.toBeNull();
  const updateControls = within(updateForm!);
  fireEvent.change(updateControls.getByRole("textbox", { name: "Streamer name" }), {
    target: { value: "Renamed Streamer" },
  });
  fireEvent.change(
    updateControls.getByRole("textbox", {
      name: "Operator reason for Existing Streamer",
    }),
    { target: { value: "Clarify the channel owner" } },
  );
  fireEvent.click(saveButton);

  await waitFor(() => expect(updateRequests).toHaveLength(1));
  expect(updateRequests[0]).toEqual({
    body: { name: "Renamed Streamer", publishProfileId: 7 },
    reason: "Clarify%20the%20channel%20owner",
  });
});
