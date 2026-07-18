import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { delay, http, HttpResponse } from "msw";
import { expect, it } from "vitest";

import { PublishingConfigurationConsole } from "@/screens/publishing-configuration-console";
import { server } from "@/test/server";

const objectDestinations = [
  {
    id: 11,
    key: "remote-object",
    name: "Remote Object",
    connectionRef: "remote-object",
    createdAt: "2026-07-18T00:00:00Z",
  },
  {
    id: 12,
    key: "local-object",
    name: "Local Object",
    connectionRef: "local-object",
    createdAt: "2026-07-18T00:00:00Z",
  },
];

const catalogDestinations = [
  {
    id: 21,
    key: "remote-catalog",
    name: "Remote Catalog",
    connectionRef: "remote-catalog",
    createdAt: "2026-07-18T00:00:00Z",
  },
  {
    id: 22,
    key: "local-catalog",
    name: "Local Catalog",
    connectionRef: "local-catalog",
    createdAt: "2026-07-18T00:00:00Z",
  },
];

function renderConsole() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <PublishingConfigurationConsole />
      </QueryClientProvider>,
    ),
  };
}

it("offers activation only for draft revisions", async () => {
  server.use(
    http.get("/ops/api/backend/ops/publish/connections", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get("/ops/api/backend/ops/publish/object-destinations", () =>
      HttpResponse.json(objectDestinations),
    ),
    http.get("/ops/api/backend/ops/publish/catalog-destinations", () =>
      HttpResponse.json(catalogDestinations),
    ),
    http.get("/ops/api/backend/ops/publish/profiles", () =>
      HttpResponse.json([
        {
          id: 7,
          key: "archive-prod",
          name: "Archive Production",
          description: null,
          activeRevisionId: null,
          createdAt: "2026-07-18T00:00:00Z",
        },
      ]),
    ),
    http.get("/ops/api/backend/ops/publish/profiles/7", () =>
      HttpResponse.json({
        id: 7,
        key: "archive-prod",
        name: "Archive Production",
        description: null,
        activeRevisionId: null,
        createdAt: "2026-07-18T00:00:00Z",
        revisions: [
          {
            id: 31,
            profileId: 7,
            revisionNumber: 1,
            state: "draft",
            routes: [],
            activatedAt: null,
            createdAt: "2026-07-18T00:00:00Z",
          },
          {
            id: 32,
            profileId: 7,
            revisionNumber: 2,
            state: "retired",
            routes: [],
            activatedAt: "2026-07-18T01:00:00Z",
            createdAt: "2026-07-18T00:30:00Z",
          },
        ],
      }),
    ),
  );

  renderConsole();
  const profileSelect = await screen.findByRole("combobox", {
    name: "Selected publication profile",
  });
  await waitFor(() => expect(profileSelect.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(profileSelect, { target: { value: "7" } });

  await waitFor(() =>
    expect(screen.getAllByRole("button", { name: "Activate" })).toHaveLength(1),
  );
});

it("submits multiple routes with independent object and catalog bindings", async () => {
  let objectDestinationRequestCount = 0;
  const revisionRequests: Array<Record<string, unknown>> = [];
  server.use(
    http.get("/ops/api/backend/ops/publish/connections", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
    http.get("/ops/api/backend/ops/publish/object-destinations", async () => {
      objectDestinationRequestCount += 1;
      if (objectDestinationRequestCount > 1) await delay(30);
      return HttpResponse.json(objectDestinations);
    }),
    http.get("/ops/api/backend/ops/publish/catalog-destinations", () =>
      HttpResponse.json(catalogDestinations),
    ),
    http.get("/ops/api/backend/ops/publish/profiles", () =>
      HttpResponse.json([
        {
          id: 7,
          key: "archive-prod",
          name: "Archive Production",
          description: null,
          activeRevisionId: null,
          createdAt: "2026-07-18T00:00:00Z",
        },
      ]),
    ),
    http.get("/ops/api/backend/ops/publish/profiles/7", () =>
      HttpResponse.json({
        id: 7,
        key: "archive-prod",
        name: "Archive Production",
        description: null,
        activeRevisionId: null,
        createdAt: "2026-07-18T00:00:00Z",
        revisions: [],
      }),
    ),
    http.post("/ops/api/backend/ops/publish/profiles/7/revisions", async ({ request }) => {
      revisionRequests.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({
        id: 31,
        profileId: 7,
        revisionNumber: 1,
        state: "draft",
        routes: [],
        activatedAt: null,
        createdAt: "2026-07-18T00:00:00Z",
      });
    }),
  );

  const { client } = renderConsole();
  const profileSelect = await screen.findByRole("combobox", {
    name: "Selected publication profile",
  });
  await waitFor(() => expect(profileSelect.querySelectorAll("option")).toHaveLength(2));
  fireEvent.change(profileSelect, { target: { value: "7" } });

  const routeOne = screen.getByRole("group", { name: "Route 1" });
  fireEvent.change(
    within(routeOne).getByRole("combobox", { name: "Object Destination 1" }),
    { target: { value: "11" } },
  );
  fireEvent.click(within(routeOne).getByRole("button", { name: "Add Object Destination" }));
  fireEvent.change(
    within(routeOne).getByRole("combobox", { name: "Object Destination 2" }),
    { target: { value: "12" } },
  );
  fireEvent.change(within(routeOne).getByRole("textbox", { name: "Key Prefix 2" }), {
    target: { value: "local-mirror" },
  });
  fireEvent.click(
    within(routeOne).getByRole("radio", { name: "Primary Object Destination 2" }),
  );
  fireEvent.click(
    within(routeOne).getByRole("checkbox", { name: "Required Object Destination 2" }),
  );

  fireEvent.click(within(routeOne).getByRole("button", { name: "Add Catalog Destination" }));
  fireEvent.change(
    within(routeOne).getByRole("combobox", { name: "Catalog Destination 1" }),
    { target: { value: "21" } },
  );
  fireEvent.change(
    within(routeOne).getByRole("combobox", { name: "Source Object Destination 1" }),
    { target: { value: "11" } },
  );
  fireEvent.click(within(routeOne).getByRole("button", { name: "Add Catalog Destination" }));
  fireEvent.change(
    within(routeOne).getByRole("combobox", { name: "Catalog Destination 2" }),
    { target: { value: "22" } },
  );
  fireEvent.change(
    within(routeOne).getByRole("combobox", { name: "Source Object Destination 2" }),
    { target: { value: "12" } },
  );
  fireEvent.click(
    within(routeOne).getByRole("checkbox", { name: "Required Catalog Destination 2" }),
  );

  fireEvent.click(screen.getByRole("button", { name: "Add Route" }));
  const routeTwo = screen.getByRole("group", { name: "Route 2" });
  fireEvent.change(
    within(routeTwo).getByRole("combobox", { name: "Object Destination 1" }),
    { target: { value: "12" } },
  );

  const submit = screen.getByRole("button", { name: "Create Draft Revision" });
  const revisionForm = submit.closest("form");
  expect(revisionForm).not.toBeNull();
  fireEvent.change(
    within(revisionForm!).getByRole("textbox", { name: "Operator reason" }),
    { target: { value: "Add local and remote publication routes" } },
  );
  fireEvent.click(submit);
  expect(revisionRequests).toHaveLength(0);
  const validationAlert = await screen.findByRole("alert");
  expect(validationAlert.textContent).toContain("unique publish mode and environment pair");

  fireEvent.change(within(routeTwo).getByRole("combobox", { name: "Publish Mode" }), {
    target: { value: "dev" },
  });
  const environment = within(routeTwo).getByRole("textbox", {
    name: "Environment",
  }) as HTMLInputElement;
  fireEvent.change(environment, { target: { value: "staging" } });
  environment.focus();
  environment.setSelectionRange(2, 5);
  await act(async () => {
    await client.invalidateQueries({ queryKey: ["publishing", "configuration"] });
  });
  await waitFor(() => expect(client.isFetching()).toBe(0));
  expect(
    within(screen.getByRole("group", { name: "Route 2" })).getByRole("textbox", {
      name: "Environment",
    }),
  ).toBe(environment);
  expect(document.activeElement).toBe(environment);
  expect(environment.selectionStart).toBe(2);
  expect(environment.selectionEnd).toBe(5);

  fireEvent.click(submit);
  await waitFor(() => expect(revisionRequests).toHaveLength(1));
  expect(revisionRequests[0]).toEqual({
    routes: [
      {
        publishMode: "prod",
        environment: "prod",
        objectBindings: [
          {
            destinationId: 11,
            keyPrefix: "archive",
            required: true,
            isPrimary: false,
          },
          {
            destinationId: 12,
            keyPrefix: "local-mirror",
            required: false,
            isPrimary: true,
          },
        ],
        catalogBindings: [
          { destinationId: 21, sourceObjectDestinationId: 11, required: true },
          { destinationId: 22, sourceObjectDestinationId: 12, required: false },
        ],
      },
      {
        publishMode: "dev",
        environment: "staging",
        objectBindings: [
          {
            destinationId: 12,
            keyPrefix: "archive",
            required: true,
            isPrimary: true,
          },
        ],
        catalogBindings: [],
      },
    ],
  });
}, 15_000);
