"use client";

import { type FormEvent, useRef, useState } from "react";

import { ActionDialog } from "@/components/action-dialog";
import { ErrorNotice, RefreshStatus } from "@/components/async-state";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import {
  type CatalogDestination,
  type ObjectDestination,
  useActivatePublishProfileRevision,
  useCatalogDestinations,
  useCreateCatalogDestination,
  useCreateObjectDestination,
  useCreatePublishProfile,
  useCreatePublishProfileRevision,
  useObjectDestinations,
  usePublicationConnections,
  usePublishProfileDetail,
  usePublishProfiles,
} from "@/features/publishing/api";

const controlClass =
  "min-h-10 w-full min-w-0 max-w-full rounded-md border bg-[var(--surface)] px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]";

interface ObjectBindingDraft {
  id: string;
  destinationId: string;
  keyPrefix: string;
  required: boolean;
  isPrimary: boolean;
}

interface CatalogBindingDraft {
  id: string;
  destinationId: string;
  sourceObjectDestinationId: string;
  required: boolean;
}

interface RouteDraft {
  id: string;
  publishMode: "prod" | "dev";
  environment: string;
  objectBindings: ObjectBindingDraft[];
  catalogBindings: CatalogBindingDraft[];
}

function initialRouteDraft(): RouteDraft {
  return {
    id: "route-initial",
    publishMode: "prod",
    environment: "prod",
    objectBindings: [
      {
        id: "object-initial",
        destinationId: "",
        keyPrefix: "archive",
        required: true,
        isPrimary: true,
      },
    ],
    catalogBindings: [],
  };
}

export function PublishingConfigurationConsole() {
  const connections = usePublicationConnections();
  const objectDestinations = useObjectDestinations();
  const catalogDestinations = useCatalogDestinations();
  const profiles = usePublishProfiles();
  const [profileId, setProfileId] = useState<number | null>(null);
  const [routes, setRoutes] = useState<RouteDraft[]>(() => [initialRouteDraft()]);
  const [revisionValidationError, setRevisionValidationError] = useState<string | null>(null);
  const nextDraftId = useRef(1);
  const revisionValidationRef = useRef<HTMLDivElement>(null);
  const profile = usePublishProfileDetail(profileId);

  const createObjectDestination = useCreateObjectDestination();
  const createCatalogDestination = useCreateCatalogDestination();
  const createProfile = useCreatePublishProfile();
  const createRevision = useCreatePublishProfileRevision(profileId ?? 0);
  const activateRevision = useActivatePublishProfileRevision(profileId ?? 0);
  const refreshing =
    connections.isFetching ||
    objectDestinations.isFetching ||
    catalogDestinations.isFetching ||
    profiles.isFetching ||
    profile.isFetching;

  function draftId(prefix: "route" | "object" | "catalog") {
    const id = nextDraftId.current;
    nextDraftId.current += 1;
    return `${prefix}-${id}`;
  }

  function replaceRoutes(update: (current: RouteDraft[]) => RouteDraft[]) {
    setRevisionValidationError(null);
    setRoutes(update);
  }

  function updateRoute(routeId: string, nextRoute: RouteDraft) {
    replaceRoutes((current) =>
      current.map((route) => (route.id === routeId ? nextRoute : route)),
    );
  }

  function addRoute() {
    const routeId = draftId("route");
    const objectId = draftId("object");
    replaceRoutes((current) => [
      ...current,
      {
        id: routeId,
        publishMode: "prod",
        environment: "prod",
        objectBindings: [
          {
            id: objectId,
            destinationId: "",
            keyPrefix: "archive",
            required: true,
            isPrimary: true,
          },
        ],
        catalogBindings: [],
      },
    ]);
  }

  function addObjectBinding(routeId: string) {
    const id = draftId("object");
    replaceRoutes((current) =>
      current.map((route) =>
        route.id === routeId
          ? {
              ...route,
              objectBindings: [
                ...route.objectBindings,
                {
                  id,
                  destinationId: "",
                  keyPrefix: "archive",
                  required: true,
                  isPrimary: false,
                },
              ],
            }
          : route,
      ),
    );
  }

  function addCatalogBinding(routeId: string) {
    const id = draftId("catalog");
    replaceRoutes((current) =>
      current.map((route) => {
        if (route.id !== routeId) return route;
        const sourceObjectDestinationId =
          route.objectBindings.find((binding) => binding.isPrimary)?.destinationId ?? "";
        return {
          ...route,
          catalogBindings: [
            ...route.catalogBindings,
            {
              id,
              destinationId: "",
              sourceObjectDestinationId,
              required: true,
            },
          ],
        };
      }),
    );
  }

  async function submitDestination(
    event: FormEvent<HTMLFormElement>,
    kind: "object" | "catalog",
  ) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const body = {
      key: String(data.get("key")),
      name: String(data.get("name")),
      connectionRef: String(data.get("connectionRef")),
    };
    const reason = String(data.get("reason"));
    try {
      if (kind === "object") {
        await createObjectDestination.mutateAsync({ body, reason });
      } else {
        await createCatalogDestination.mutateAsync({ body, reason });
      }
      form.reset();
    } catch {
      /* The inline mutation error remains visible beside this form. */
    }
  }

  async function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    try {
      const created = await createProfile.mutateAsync({
        body: {
          key: String(data.get("key")),
          name: String(data.get("name")),
          description: String(data.get("description")) || null,
        },
        reason: String(data.get("reason")),
      });
      setProfileId(created.id);
      form.reset();
    } catch {
      /* The inline mutation error remains visible beside this form. */
    }
  }

  async function submitRevision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (profileId === null) return;
    const validationError = validateRoutes(routes);
    if (validationError) {
      setRevisionValidationError(validationError);
      requestAnimationFrame(() => revisionValidationRef.current?.focus());
      return;
    }

    const form = event.currentTarget;
    const data = new FormData(form);
    setRevisionValidationError(null);
    try {
      await createRevision.mutateAsync({
        body: {
          routes: routes.map((route) => ({
            publishMode: route.publishMode,
            environment: route.environment.trim(),
            objectBindings: route.objectBindings.map((binding) => ({
              destinationId: Number(binding.destinationId),
              keyPrefix: binding.keyPrefix.trim().replace(/^\/+|\/+$/g, ""),
              required: binding.required,
              isPrimary: binding.isPrimary,
            })),
            catalogBindings: route.catalogBindings.map((binding) => ({
              destinationId: Number(binding.destinationId),
              sourceObjectDestinationId: Number(binding.sourceObjectDestinationId),
              required: binding.required,
            })),
          })),
        },
        reason: String(data.get("reason")),
      });
      setRoutes([initialRouteDraft()]);
      form.reset();
    } catch {
      /* The inline mutation error remains visible beside this form. */
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Configuration"
        heading="Publishing Routes"
        description="Manage safe connection references, destination bindings, and activated publication profile revisions."
      />
      <div
        className="mb-4 flex min-h-6 items-center gap-2 text-sm text-[var(--muted)]"
        aria-live="polite"
      >
        <RefreshStatus refreshing={refreshing} />
        <span>
          {refreshing
            ? "Refreshing route configuration…"
            : "Connection secrets are never displayed in this console."}
        </span>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <DestinationPanel
          title="Object Destination"
          kind="object"
          connections={connections.data?.items ?? []}
          pending={createObjectDestination.isPending}
          error={createObjectDestination.error?.message ?? null}
          onSubmit={submitDestination}
        />
        <DestinationPanel
          title="Catalog Destination"
          kind="catalog"
          connections={connections.data?.items ?? []}
          pending={createCatalogDestination.isPending}
          error={createCatalogDestination.error?.message ?? null}
          onSubmit={submitDestination}
        />
      </div>
      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <Panel.Root>
          <Panel.Header>
            <Panel.HeadingGroup>
              <Panel.Title>Create Publication Profile</Panel.Title>
              <Panel.Description>
                Create a named profile before assigning it to a streamer.
              </Panel.Description>
            </Panel.HeadingGroup>
          </Panel.Header>
          <Panel.Body>
            <form className="grid gap-3" onSubmit={submitProfile}>
              <TextField
                label="Profile key"
                name="key"
                pattern="[a-z0-9][a-z0-9-]*"
                placeholder="archive-prod"
              />
              <TextField label="Profile name" name="name" placeholder="Archive production" />
              <label className="grid gap-1 text-sm font-medium">
                Description
                <textarea
                  name="description"
                  className={`${controlClass} min-h-20 py-2`}
                  autoComplete="off"
                  placeholder="Purpose & ownership…"
                />
              </label>
              <ReasonField />
              {createProfile.error && <ErrorNotice message={createProfile.error.message} />}
              <Button type="submit" variant="primary" disabled={createProfile.isPending}>
                {createProfile.isPending ? "Creating…" : "Create Profile"}
              </Button>
            </form>
          </Panel.Body>
        </Panel.Root>
        <Panel.Root>
          <Panel.Header>
            <Panel.HeadingGroup>
              <Panel.Title>Profile Revision</Panel.Title>
              <Panel.Description>
                Draft one or more mode and environment routes, then activate the complete revision.
              </Panel.Description>
            </Panel.HeadingGroup>
          </Panel.Header>
          <Panel.Body>
            <label className="mb-3 grid gap-1 text-sm font-medium">
              Profile
              <select
                value={profileId ?? ""}
                onChange={(event) =>
                  setProfileId(event.target.value ? Number(event.target.value) : null)
                }
                className={controlClass}
                aria-label="Selected publication profile"
              >
                <option value="">Select a profile…</option>
                {profiles.data?.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name} ({item.key})
                  </option>
                ))}
              </select>
            </label>
            {profiles.error && <ErrorNotice message={profiles.error.message} />}
            <form className="grid gap-4" onSubmit={submitRevision}>
              <div className="grid gap-4">
                {routes.map((route, index) => (
                  <RouteDraftEditor
                    key={route.id}
                    index={index}
                    route={route}
                    routeCount={routes.length}
                    objectDestinations={objectDestinations.data ?? []}
                    catalogDestinations={catalogDestinations.data ?? []}
                    onChange={(nextRoute) => updateRoute(route.id, nextRoute)}
                    onAddObject={() => addObjectBinding(route.id)}
                    onAddCatalog={() => addCatalogBinding(route.id)}
                    onRemove={() =>
                      replaceRoutes((current) =>
                        current.filter((candidate) => candidate.id !== route.id),
                      )
                    }
                  />
                ))}
              </div>
              <Button type="button" variant="outline" onClick={addRoute}>
                Add Route
              </Button>
              <ReasonField />
              {revisionValidationError && (
                <div
                  ref={revisionValidationRef}
                  tabIndex={-1}
                  className="rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
                >
                  <ErrorNotice message={revisionValidationError} />
                </div>
              )}
              {createRevision.error && <ErrorNotice message={createRevision.error.message} />}
              <Button
                type="submit"
                variant="primary"
                disabled={
                  profileId === null ||
                  createRevision.isPending ||
                  objectDestinations.data?.length === 0
                }
              >
                {createRevision.isPending ? "Saving revision…" : "Create Draft Revision"}
              </Button>
            </form>
            <div className="mt-4 grid gap-2 border-t pt-4">
              {profile.error && <ErrorNotice message={profile.error.message} />}
              {profile.data?.revisions.map((revision) => (
                <div
                  key={revision.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3"
                >
                  <div className="min-w-0">
                    <p className="font-medium">
                      Revision {revision.revisionNumber} <StatusBadge value={revision.state} />
                    </p>
                    <p className="truncate font-mono text-xs text-[var(--muted)]">
                      {revision.routes
                        .map(
                          (route) =>
                            `${route.publishMode}/${route.environment} (${route.objectBindings.length} object, ${route.catalogBindings.length} catalog)`,
                        )
                        .join(", ") || "No routes"}
                    </p>
                  </div>
                  {revision.state === "draft" && (
                    <ActionDialog.Provider
                      heading={`Activate revision ${revision.revisionNumber}`}
                      description="Activate this revision for future streamer publication routes."
                      confirmLabel="Activate"
                      confirmationValue={String(revision.id)}
                      reasonRequired
                      onConfirm={(reason) =>
                        activateRevision
                          .mutateAsync({ revisionId: revision.id, reason })
                          .then(() => undefined)
                      }
                    >
                      <ActionDialog.Trigger>
                        <Button size="sm" disabled={activateRevision.isPending}>
                          Activate
                        </Button>
                      </ActionDialog.Trigger>
                      <ActionDialog.Content>
                        <ActionDialog.ConfirmationField />
                        <ActionDialog.ReasonField />
                        <ActionDialog.ErrorMessage />
                        <ActionDialog.Footer />
                      </ActionDialog.Content>
                    </ActionDialog.Provider>
                  )}
                </div>
              ))}
              {profile.data && profile.data.revisions.length === 0 && (
                <p className="text-sm text-[var(--muted)]">No revisions yet.</p>
              )}
            </div>
          </Panel.Body>
        </Panel.Root>
      </div>
    </>
  );
}

function RouteDraftEditor({
  index,
  route,
  routeCount,
  objectDestinations,
  catalogDestinations,
  onChange,
  onAddObject,
  onAddCatalog,
  onRemove,
}: {
  index: number;
  route: RouteDraft;
  routeCount: number;
  objectDestinations: ObjectDestination[];
  catalogDestinations: CatalogDestination[];
  onChange: (route: RouteDraft) => void;
  onAddObject: () => void;
  onAddCatalog: () => void;
  onRemove: () => void;
}) {
  const routeNumber = index + 1;

  function updateObjectBinding(bindingId: string, update: Partial<ObjectBindingDraft>) {
    const previous = route.objectBindings.find((binding) => binding.id === bindingId);
    const nextObjectBindings = route.objectBindings.map((binding) =>
      binding.id === bindingId ? { ...binding, ...update } : binding,
    );
    let nextCatalogBindings = route.catalogBindings;
    if (previous && update.destinationId !== undefined) {
      nextCatalogBindings = route.catalogBindings.map((binding) =>
        binding.sourceObjectDestinationId === previous.destinationId
          ? { ...binding, sourceObjectDestinationId: update.destinationId ?? "" }
          : binding,
      );
    }
    onChange({
      ...route,
      objectBindings: nextObjectBindings,
      catalogBindings: nextCatalogBindings,
    });
  }

  function selectPrimaryObject(bindingId: string) {
    onChange({
      ...route,
      objectBindings: route.objectBindings.map((binding) => ({
        ...binding,
        isPrimary: binding.id === bindingId,
      })),
    });
  }

  function removeObjectBinding(bindingId: string) {
    const removed = route.objectBindings.find((binding) => binding.id === bindingId);
    let remaining = route.objectBindings.filter((binding) => binding.id !== bindingId);
    if (!remaining.some((binding) => binding.isPrimary) && remaining.length > 0) {
      remaining = remaining.map((binding, bindingIndex) => ({
        ...binding,
        isPrimary: bindingIndex === 0,
      }));
    }
    const replacementSource =
      remaining.find((binding) => binding.isPrimary)?.destinationId ?? "";
    onChange({
      ...route,
      objectBindings: remaining,
      catalogBindings: route.catalogBindings.map((binding) =>
        removed && binding.sourceObjectDestinationId === removed.destinationId
          ? { ...binding, sourceObjectDestinationId: replacementSource }
          : binding,
      ),
    });
  }

  function updateCatalogBinding(bindingId: string, update: Partial<CatalogBindingDraft>) {
    onChange({
      ...route,
      catalogBindings: route.catalogBindings.map((binding) =>
        binding.id === bindingId ? { ...binding, ...update } : binding,
      ),
    });
  }

  return (
    <fieldset className="grid min-w-0 gap-4 rounded-md border p-4">
      <legend className="px-1 text-sm font-semibold">Route {routeNumber}</legend>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-sm font-medium">
            Publish Mode
            <select
              name={`route-${route.id}-publish-mode`}
              className={controlClass}
              value={route.publishMode}
              onChange={(event) =>
                onChange({
                  ...route,
                  publishMode: event.target.value === "dev" ? "dev" : "prod",
                })
              }
            >
              <option value="prod">prod</option>
              <option value="dev">dev</option>
            </select>
          </label>
          <label className="grid gap-1 text-sm font-medium">
            Environment
            <input
              name={`route-${route.id}-environment`}
              value={route.environment}
              onChange={(event) => onChange({ ...route, environment: event.target.value })}
              required
              maxLength={64}
              className={controlClass}
              autoComplete="off"
              placeholder="prod…"
            />
          </label>
        </div>
        {routeCount > 1 && (
          <Button type="button" variant="ghost" size="sm" onClick={onRemove}>
            Remove Route {routeNumber}
          </Button>
        )}
      </div>

      <fieldset className="grid min-w-0 gap-3 rounded-md border border-dashed p-3">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          Object Destinations
        </legend>
        {route.objectBindings.map((binding, bindingIndex) => {
          const usedDestinationIds = new Set(
            route.objectBindings
              .filter((candidate) => candidate.id !== binding.id)
              .map((candidate) => candidate.destinationId)
              .filter(Boolean),
          );
          return (
            <div
              key={binding.id}
              className="grid min-w-0 gap-3 rounded-md bg-[var(--surface-muted)] p-3"
            >
              <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                <label className="grid gap-1 text-sm font-medium">
                  Object Destination {bindingIndex + 1}
                  <select
                    name={`route-${route.id}-object-${binding.id}-destination`}
                    className={controlClass}
                    required
                    value={binding.destinationId}
                    onChange={(event) =>
                      updateObjectBinding(binding.id, { destinationId: event.target.value })
                    }
                    disabled={objectDestinations.length === 0}
                  >
                    <option value="" disabled>
                      Select a destination…
                    </option>
                    {binding.destinationId &&
                      !objectDestinations.some(
                        (destination) => String(destination.id) === binding.destinationId,
                      ) && (
                        <option value={binding.destinationId}>
                          Unavailable destination #{binding.destinationId}
                        </option>
                      )}
                    {objectDestinations.map((destination) => (
                      <option
                        key={destination.id}
                        value={destination.id}
                        disabled={usedDestinationIds.has(String(destination.id))}
                      >
                        {destination.name} ({destination.key})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-1 text-sm font-medium">
                  Key Prefix {bindingIndex + 1}
                  <input
                    name={`route-${route.id}-object-${binding.id}-key-prefix`}
                    value={binding.keyPrefix}
                    onChange={(event) =>
                      updateObjectBinding(binding.id, { keyPrefix: event.target.value })
                    }
                    required
                    maxLength={512}
                    className={controlClass}
                    autoComplete="off"
                    placeholder="archive…"
                  />
                </label>
              </div>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                <label className="inline-flex min-h-11 items-center gap-2 text-sm font-medium sm:min-h-8">
                  <input
                    type="checkbox"
                    name={`route-${route.id}-object-${binding.id}-required`}
                    checked={binding.required}
                    onChange={(event) =>
                      updateObjectBinding(binding.id, { required: event.target.checked })
                    }
                  />
                  Required Object Destination {bindingIndex + 1}
                </label>
                <label className="inline-flex min-h-11 items-center gap-2 text-sm font-medium sm:min-h-8">
                  <input
                    type="radio"
                    name={`route-${route.id}-primary-object`}
                    value={binding.id}
                    checked={binding.isPrimary}
                    onChange={() => selectPrimaryObject(binding.id)}
                  />
                  Primary Object Destination {bindingIndex + 1}
                </label>
                {route.objectBindings.length > 1 && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => removeObjectBinding(binding.id)}
                  >
                    Remove Object Destination {bindingIndex + 1}
                  </Button>
                )}
              </div>
            </div>
          );
        })}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onAddObject}
          disabled={route.objectBindings.length >= objectDestinations.length}
        >
          Add Object Destination
        </Button>
      </fieldset>

      <fieldset className="grid min-w-0 gap-3 rounded-md border border-dashed p-3">
        <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
          Catalog Destinations
        </legend>
        {route.catalogBindings.length === 0 && (
          <p className="text-sm text-[var(--muted)]">
            No catalog destination is included in this route.
          </p>
        )}
        {route.catalogBindings.map((binding, bindingIndex) => {
          const usedDestinationIds = new Set(
            route.catalogBindings
              .filter((candidate) => candidate.id !== binding.id)
              .map((candidate) => candidate.destinationId)
              .filter(Boolean),
          );
          return (
            <div
              key={binding.id}
              className="grid min-w-0 gap-3 rounded-md bg-[var(--surface-muted)] p-3"
            >
              <div className="grid min-w-0 gap-3 sm:grid-cols-2">
                <label className="grid gap-1 text-sm font-medium">
                  Catalog Destination {bindingIndex + 1}
                  <select
                    name={`route-${route.id}-catalog-${binding.id}-destination`}
                    className={controlClass}
                    required
                    value={binding.destinationId}
                    onChange={(event) =>
                      updateCatalogBinding(binding.id, { destinationId: event.target.value })
                    }
                    disabled={catalogDestinations.length === 0}
                  >
                    <option value="" disabled>
                      Select a destination…
                    </option>
                    {binding.destinationId &&
                      !catalogDestinations.some(
                        (destination) => String(destination.id) === binding.destinationId,
                      ) && (
                        <option value={binding.destinationId}>
                          Unavailable destination #{binding.destinationId}
                        </option>
                      )}
                    {catalogDestinations.map((destination) => (
                      <option
                        key={destination.id}
                        value={destination.id}
                        disabled={usedDestinationIds.has(String(destination.id))}
                      >
                        {destination.name} ({destination.key})
                      </option>
                    ))}
                  </select>
                </label>
                <label className="grid gap-1 text-sm font-medium">
                  Source Object Destination {bindingIndex + 1}
                  <select
                    name={`route-${route.id}-catalog-${binding.id}-source-object`}
                    className={controlClass}
                    required
                    value={binding.sourceObjectDestinationId}
                    onChange={(event) =>
                      updateCatalogBinding(binding.id, {
                        sourceObjectDestinationId: event.target.value,
                      })
                    }
                  >
                    <option value="" disabled>
                      Select an object destination…
                    </option>
                    {route.objectBindings
                      .filter((objectBinding) => objectBinding.destinationId)
                      .map((objectBinding) => {
                        const destination = objectDestinations.find(
                          (candidate) => String(candidate.id) === objectBinding.destinationId,
                        );
                        return (
                          <option key={objectBinding.id} value={objectBinding.destinationId}>
                            {destination?.name ??
                              `Unavailable destination #${objectBinding.destinationId}`}
                          </option>
                        );
                      })}
                  </select>
                </label>
              </div>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
                <label className="inline-flex min-h-11 items-center gap-2 text-sm font-medium sm:min-h-8">
                  <input
                    type="checkbox"
                    name={`route-${route.id}-catalog-${binding.id}-required`}
                    checked={binding.required}
                    onChange={(event) =>
                      updateCatalogBinding(binding.id, { required: event.target.checked })
                    }
                  />
                  Required Catalog Destination {bindingIndex + 1}
                </label>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    onChange({
                      ...route,
                      catalogBindings: route.catalogBindings.filter(
                        (candidate) => candidate.id !== binding.id,
                      ),
                    })
                  }
                >
                  Remove Catalog Destination {bindingIndex + 1}
                </Button>
              </div>
            </div>
          );
        })}
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onAddCatalog}
          disabled={
            route.catalogBindings.length >= catalogDestinations.length ||
            !route.objectBindings.some((binding) => binding.destinationId)
          }
        >
          Add Catalog Destination
        </Button>
      </fieldset>
    </fieldset>
  );
}

function validateRoutes(routes: RouteDraft[]): string | null {
  if (routes.length === 0) return "Add at least 1 publication route before saving.";
  const routeKeys = new Set<string>();

  for (const [routeIndex, route] of routes.entries()) {
    const routeLabel = `Route ${routeIndex + 1}`;
    const environment = route.environment.trim();
    if (!environment) return `${routeLabel}: Enter an environment.`;
    const routeKey = `${route.publishMode}\u0000${environment}`;
    if (routeKeys.has(routeKey)) {
      return `${routeLabel}: Choose a unique publish mode and environment pair.`;
    }
    routeKeys.add(routeKey);

    if (route.objectBindings.length === 0) {
      return `${routeLabel}: Add at least 1 object destination.`;
    }
    if (route.objectBindings.some((binding) => !binding.destinationId)) {
      return `${routeLabel}: Select every object destination.`;
    }
    const objectDestinationIds = route.objectBindings.map(
      (binding) => binding.destinationId,
    );
    if (new Set(objectDestinationIds).size !== objectDestinationIds.length) {
      return `${routeLabel}: Use each object destination only once.`;
    }
    if (route.objectBindings.filter((binding) => binding.isPrimary).length !== 1) {
      return `${routeLabel}: Select exactly 1 primary object destination.`;
    }
    if (
      route.objectBindings.some(
        (binding) => binding.keyPrefix.trim().replace(/^\/+|\/+$/g, "").length === 0,
      )
    ) {
      return `${routeLabel}: Enter a non-empty key prefix for every object destination.`;
    }

    if (route.catalogBindings.some((binding) => !binding.destinationId)) {
      return `${routeLabel}: Select every catalog destination.`;
    }
    const catalogDestinationIds = route.catalogBindings.map(
      (binding) => binding.destinationId,
    );
    if (new Set(catalogDestinationIds).size !== catalogDestinationIds.length) {
      return `${routeLabel}: Use each catalog destination only once.`;
    }
    if (
      route.catalogBindings.some(
        (binding) =>
          !binding.sourceObjectDestinationId ||
          !objectDestinationIds.includes(binding.sourceObjectDestinationId),
      )
    ) {
      return `${routeLabel}: Link every catalog destination to an object destination in the same route.`;
    }
  }
  return null;
}

function DestinationPanel({
  title,
  kind,
  connections,
  pending,
  error,
  onSubmit,
}: {
  title: string;
  kind: "object" | "catalog";
  connections: Array<{
    connectionRef: string;
    target: string;
    kind: string;
    configured: boolean;
  }>;
  pending: boolean;
  error: string | null;
  onSubmit: (
    event: FormEvent<HTMLFormElement>,
    kind: "object" | "catalog",
  ) => Promise<void>;
}) {
  const compatible = connections.filter((connection) =>
    kind === "object"
      ? connection.kind === "s3_compatible_object"
      : connection.kind !== "s3_compatible_object",
  );
  return (
    <Panel.Root>
      <Panel.Header>
        <Panel.HeadingGroup>
          <Panel.Title>{title}</Panel.Title>
          <Panel.Description>
            Use an existing configured connection reference; credentials remain server-side.
          </Panel.Description>
        </Panel.HeadingGroup>
      </Panel.Header>
      <Panel.Body>
        <form className="grid gap-3" onSubmit={(event) => void onSubmit(event, kind)}>
          <TextField
            label="Destination key"
            name="key"
            pattern="[a-z0-9][a-z0-9-]*"
            placeholder="public-archive"
          />
          <TextField label="Destination name" name="name" placeholder="Public Archive" />
          <label className="grid gap-1 text-sm font-medium">
            Connection reference
            <select
              name="connectionRef"
              className={controlClass}
              required
              defaultValue=""
              disabled={compatible.length === 0}
            >
              <option value="" disabled>
                {compatible.length ? "Select a configured connection…" : "No compatible connection"}
              </option>
              {compatible.map((connection) => (
                <option
                  key={connection.connectionRef}
                  value={connection.connectionRef}
                  disabled={!connection.configured}
                >
                  {connection.connectionRef} — {connection.target}
                  {connection.configured ? "" : " (not configured)"}
                </option>
              ))}
            </select>
          </label>
          <ReasonField />
          {error && <ErrorNotice message={error} />}
          <Button type="submit" variant="primary" disabled={pending || compatible.length === 0}>
            {pending ? "Creating…" : `Create ${title}`}
          </Button>
        </form>
      </Panel.Body>
    </Panel.Root>
  );
}

function TextField({
  label,
  name,
  defaultValue,
  pattern,
  placeholder,
}: {
  label: string;
  name: string;
  defaultValue?: string;
  pattern?: string;
  placeholder: string;
}) {
  return (
    <label className="grid gap-1 text-sm font-medium">
      {label}
      <input
        name={name}
        defaultValue={defaultValue}
        pattern={pattern}
        required
        className={controlClass}
        autoComplete="off"
        placeholder={`${placeholder}…`}
      />
    </label>
  );
}

function ReasonField() {
  return (
    <label className="grid gap-1 text-sm font-medium">
      Operator reason
      <input
        name="reason"
        required
        minLength={3}
        maxLength={500}
        className={controlClass}
        autoComplete="off"
        placeholder="Why is this change needed…"
      />
    </label>
  );
}
