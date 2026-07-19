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

function renderConsole(currentStreamers: Streamer[] = streamers) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <ChannelsConsole initialChannels={channels} initialStreamers={currentStreamers} />
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
    http.get("/ops/api/backend/ops/publish/connections", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get("/ops/api/backend/ops/publish/profiles/7", () =>
      HttpResponse.json({
        id: 7,
        key: "archive-prod",
        name: "Archive Production",
        description: null,
        activeRevisionId: 9,
        createdAt: "2026-07-18T00:00:00Z",
        revisions: [
          {
            id: 9,
            profileId: 7,
            revisionNumber: 1,
            state: "active",
            createdAt: "2026-07-18T00:00:00Z",
            activatedAt: "2026-07-18T00:00:00Z",
            routes: [],
          },
        ],
      }),
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

  const saveButton = screen.getByRole("button", { name: "Save Streamer" });
  const updateForm = saveButton.closest("form");
  expect(updateForm).not.toBeNull();
  const updateControls = within(updateForm!);
  fireEvent.change(updateControls.getByRole("textbox", { name: "Streamer Name" }), {
    target: { value: "Renamed Streamer" },
  });
  fireEvent.change(
    updateControls.getByRole("textbox", { name: "Operator Reason" }),
    { target: { value: "Clarify the channel owner" } },
  );
  fireEvent.click(saveButton);

  await waitFor(() => expect(updateRequests).toHaveLength(1));
  expect(updateRequests[0]).toEqual({
    body: { name: "Renamed Streamer", publishProfileId: 7 },
    reason: "Clarify%20the%20channel%20owner",
  });
});

it("shows the streamer's assigned profile and active local destinations instead of the first profile option", async () => {
  const rikoStreamers = [
    { id: 5, name: "유즈하 리코", publishProfileId: 2 },
  ] as Streamer[];
  server.use(
    http.get("/ops/api/backend/ops/channels", () => HttpResponse.json(channels)),
    http.get("/ops/api/backend/ops/streamers", () => HttpResponse.json(rikoStreamers)),
    http.get("/ops/api/backend/ops/publish/profiles", () =>
      HttpResponse.json([
        {
          id: 1,
          key: "legacy-current",
          name: "Legacy Current",
          description: null,
          activeRevisionId: 1,
          createdAt: "2026-07-18T00:00:00Z",
        },
        {
          id: 2,
          key: "stellive-cliche-local",
          name: "StelLive Cliche Local",
          description: "Local-only publication profile.",
          activeRevisionId: 2,
          createdAt: "2026-07-18T00:00:00Z",
        },
      ]),
    ),
    http.get("/ops/api/backend/ops/publish/connections", () =>
      HttpResponse.json({
        total: 2,
        items: [
          {
            connectionRef: "local-public-object",
            kind: "s3_compatible_object",
            target: "127.0.0.1:9000",
            publicBaseUrl: "http://127.0.0.1:9000",
            secretFields: ["accessKey", "secretKey"],
            configured: true,
          },
          {
            connectionRef: "local-public-catalog",
            kind: "sql_catalog",
            target: "postgresql+asyncpg://127.0.0.1:5432/codex_public_catalog",
            publicBaseUrl: null,
            secretFields: ["databaseUrl"],
            configured: true,
          },
        ],
      }),
    ),
    http.get("/ops/api/backend/ops/publish/profiles/2", () =>
      HttpResponse.json({
        id: 2,
        key: "stellive-cliche-local",
        name: "StelLive Cliche Local",
        description: "Local-only publication profile.",
        activeRevisionId: 2,
        createdAt: "2026-07-18T00:00:00Z",
        revisions: [
          {
            id: 2,
            profileId: 2,
            revisionNumber: 1,
            state: "active",
            createdAt: "2026-07-18T00:00:00Z",
            activatedAt: "2026-07-18T00:00:00Z",
            routes: [
              {
                id: 3,
                publishMode: "prod",
                environment: "prod",
                objectBindings: [
                  {
                    id: 5,
                    destinationId: 2,
                    destinationKey: "local-object",
                    connectionRef: "local-public-object",
                    keyPrefix: "archive/stellive-cliche",
                    required: true,
                    isPrimary: true,
                  },
                ],
                catalogBindings: [
                  {
                    id: 5,
                    destinationId: 2,
                    destinationKey: "local-catalog",
                    connectionRef: "local-public-catalog",
                    sourceObjectBindingId: 5,
                    required: true,
                  },
                ],
              },
            ],
          },
        ],
      }),
    ),
  );

  renderConsole(rikoStreamers);

  const profileSelect = await screen.findByRole("combobox", {
    name: "Publication Profile",
  });
  await waitFor(() => expect(profileSelect.querySelectorAll("option")).toHaveLength(2));
  expect((profileSelect as HTMLSelectElement).value).toBe("2");
  expect(screen.getAllByText("StelLive Cliche Local").length).toBeGreaterThan(0);
  expect(await screen.findByText("Local Only")).not.toBeNull();
  expect(screen.getByText(/local-public-object → 127\.0\.0\.1:9000/)).not.toBeNull();
  expect(screen.getByText(/local-public-catalog → postgresql\+asyncpg:\/\/127\.0\.0\.1:5432\/codex_public_catalog/)).not.toBeNull();
});
