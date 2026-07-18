"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { ActionDialog } from "@/components/action-dialog";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import type { ArchiveCurrent, ArchiveVideos, PublicationStage, PublicationStageResult, PublicationStatusList } from "@/features/publishing/api";
import { parsePublicationStatus, publicationStatusFilters, useArchiveCurrent, useArchiveVideos, usePublicationStatuses, usePublishProfiles, useRunPublicationStage } from "@/features/publishing/api";
import { useStreamers } from "@/features/catalog/api";
import { formatDateTime, formatNumber } from "@/lib/format";

type ArchiveRow = ArchiveVideos["items"][number];
const controlClass = "min-h-10 rounded-md border bg-[var(--surface)] px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]";
const stageLabels: Record<PublicationStage, string> = {
  artifactBuild: "Build artifacts",
  objectDeliver: "Deliver objects",
  catalogPublish: "Publish catalog",
  publicationBuild: "Build publication",
  pointerPublish: "Publish pointer",
};

export function PublishingConsole({ initialCurrent, initialVideos, initialPublications = null }: { initialCurrent: ArchiveCurrent | null; initialVideos: ArchiveVideos | null; initialPublications?: PublicationStatusList | null }) {
  const router = useRouter(); const pathname = usePathname(); const params = useSearchParams();
  const publishMode = params.get("mode") === "dev" ? "dev" : "prod";
  const environment = params.get("environment") ?? publishMode;
  const offset = Number(params.get("offset")) || 0;
  const streamerId = parseFilterId(params.get("streamerId"));
  const profileId = parseFilterId(params.get("profileId"));
  const publicationStatus = parsePublicationStatus(params.get("status"));
  const streamers = useStreamers();
  const profiles = usePublishProfiles();
  const current = useArchiveCurrent({ environment, publishMode, offset }, initialCurrent);
  const videos = useArchiveVideos({ environment, publishMode, offset, streamerId: streamerId ?? undefined, profileId: profileId ?? undefined }, initialVideos);
  const publications = usePublicationStatuses({ environment, publishMode, offset, streamerId: streamerId ?? undefined, profileId: profileId ?? undefined, status: publicationStatus }, initialPublications);
  function replace(values: Record<string, string | undefined>) { const next = new URLSearchParams(params); Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key)); router.replace(`${pathname}?${next.toString()}`, { scroll: false }); }
  const columns: ColumnDef<ArchiveRow>[] = [
    { header: "Video", accessorKey: "title", cell: ({ row }) => <div className="min-w-0"><Link href={`/content/videos/${row.original.videoId}`} className="font-medium hover:underline">{row.original.title}</Link><p className="font-mono text-xs text-[var(--muted)]">#{row.original.videoId} · {row.original.youtubeVideoId}</p></div> },
    { header: "Timeline", accessorKey: "timelineReady", cell: ({ row }) => <StatusBadge value={row.original.timelineReady ? "ready" : "not_ready"} /> },
    { header: "Episodes", accessorKey: "timelineEpisodeCount", cell: ({ getValue }) => <span className="ops-number">{String(getValue())}</span> },
    { header: "Artifact", accessorKey: "latestArtifact", cell: ({ row }) => <StatusBadge value={row.original.latestArtifact?.artifactStatus ?? "not_ready"} /> },
    { header: "Publish", accessorKey: "latestTask", cell: ({ row }) => <StatusBadge value={row.original.latestTask?.status ?? "not_ready"} /> },
    { header: "Artifact issue", accessorKey: "latestArtifact", cell: ({ row }) => <span className="block max-w-60 break-words font-mono text-xs text-[var(--muted)]">{row.original.latestArtifact?.unavailableCode ?? "—"}</span> },
  ];
  const publication = current.data?.latestPublication;
  return <>
    <PageHeader eyebrow="Publishing" heading="Publication Stages" description="Run publication work one recoverable stage at a time and inspect the returned destination status." actions={<div className="flex flex-wrap gap-2"><label className="sr-only" htmlFor="publish-mode">Publish mode</label><select id="publish-mode" aria-label="Publish mode" value={publishMode} onChange={(event) => replace({ mode: event.target.value, environment: event.target.value, offset: undefined })} className={`${controlClass} font-mono`}><option value="prod">prod</option><option value="dev">dev</option></select><label className="sr-only" htmlFor="publish-environment">Environment</label><input id="publish-environment" aria-label="Environment" value={environment} onChange={(event) => replace({ environment: event.target.value, offset: undefined })} className={`${controlClass} w-28 font-mono`} autoComplete="off" /><label className="sr-only" htmlFor="publish-streamer">Streamer</label><select id="publish-streamer" aria-label="Streamer" value={streamerId ?? ""} onChange={(event) => replace({ streamerId: event.target.value || undefined, offset: undefined })} className={`${controlClass} min-w-36`}><option value="">All streamers</option>{streamers.data?.map((streamer) => <option key={streamer.id} value={streamer.id}>{streamer.name}</option>)}</select><label className="sr-only" htmlFor="publish-profile">Publication profile</label><select id="publish-profile" aria-label="Publication profile" value={profileId ?? ""} onChange={(event) => replace({ profileId: event.target.value || undefined, offset: undefined })} className={`${controlClass} min-w-40`}><option value="">All profiles</option>{profiles.data?.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select><label className="sr-only" htmlFor="publication-status">Publication status</label><select id="publication-status" aria-label="Publication status" value={publicationStatus ?? ""} onChange={(event) => replace({ status: event.target.value || undefined, offset: undefined })} className={`${controlClass} min-w-36`}><option value="">All states</option>{publicationStatusFilters.map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}</select></div>} />
    <div className="mb-4 grid gap-4 md:grid-cols-3"><Metric label="Publication" value={publication ? `#${publication.publicationId}` : "None"} detail={publication ? formatDateTime(publication.createdAt) : `${environment}/${publishMode}`} /><Metric label="Videos" value={formatNumber(publication?.videoCount)} detail={publication?.version ?? "—"} /><Metric label="Storage" value={current.data?.storage.configured ? "connected" : "disabled"} detail={current.data?.storage.bucket ?? "—"} /></div>
    <PublicationStageConsole environment={environment} publishMode={publishMode} />
    <PublicationStatusConsole publications={publications} initialData={initialPublications} />
    <DataTable.Provider rows={videos.data?.items ?? []} columns={columns} getRowId={(row) => String(row.videoId)} state={{ initialLoading: videos.isLoading, refreshing: videos.isFetching && !videos.isLoading, placeholder: videos.isPlaceholderData, error: videos.error?.message ?? null }} actions={{ previous: () => replace({ offset: String(Math.max(0, offset - 50)) }), next: () => replace({ offset: String(offset + 50) }) }} meta={{ label: "Archive video publication readiness", emptyTitle: "No publication-ready videos", emptyDescription: "Build a timeline before building its publication artifact.", canPrevious: offset > 0, canNext: offset + 50 < (videos.data?.total ?? 0) }}><DataTable.Frame><DataTable.Toolbar><span className="text-sm text-[var(--muted)]">{formatNumber(videos.data?.total)} videos</span></DataTable.Toolbar><DataTable.Content /><DataTable.Pagination /></DataTable.Frame></DataTable.Provider>
  </>;
}

function PublicationStatusConsole({ publications, initialData }: { publications: ReturnType<typeof usePublicationStatuses>; initialData: PublicationStatusList | null }) {
  const data = publications.data ?? initialData;
  const rows = data?.items ?? [];
  return <Panel.Root className="mb-4"><Panel.Header><Panel.HeadingGroup><Panel.Title>Persisted Publications</Panel.Title><Panel.Description>Publication records and destination delivery outcomes use the active URL filters.</Panel.Description></Panel.HeadingGroup><span role="status" aria-live="polite" className="text-xs text-[var(--muted)]">{publications.isFetching && !publications.isLoading ? "Refreshing…" : `${formatNumber(data?.total)} records`}</span></Panel.Header><Panel.Body>{publications.error && rows.length === 0 ? <p role="alert" className="text-sm text-[var(--danger)]">{publications.error.message}</p> : publications.isLoading && rows.length === 0 ? <p role="status" className="text-sm text-[var(--muted)]">Loading publications…</p> : rows.length === 0 ? <p className="text-sm text-[var(--muted)]">No persisted publications match these filters.</p> : <div className="grid gap-3" aria-busy={publications.isFetching}>{rows.map((publication) => <article key={publication.id} className="rounded-md border p-3"><div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0"><p className="font-medium"><code translate="no">#{publication.id}</code> · {publication.profileName} <StatusBadge value={publication.status} /></p><p className="truncate font-mono text-xs text-[var(--muted)]" translate="no">{publication.profileKey} · rev {publication.profileRevisionId} · {publication.publishMode}/{publication.environment} · v{publication.version}</p></div><p className="ops-number whitespace-nowrap text-xs text-[var(--muted)]">{publication.videoCount} videos · {publication.artifactCount} artifacts</p></div>{publication.errorMessage && <p role="alert" className="mt-2 break-words text-sm text-[var(--danger)]"><code translate="no">{publication.errorCode ?? "publication.error"}</code>: {publication.errorMessage}</p>}<p className="mt-2 text-xs text-[var(--muted)]">Updated {formatDateTime(publication.updatedAt)}</p><div className="mt-3 grid gap-2 border-t pt-3">{publication.deliveries.map((delivery) => <div key={delivery.id} className="rounded border bg-[var(--surface-muted)]/45 p-2"><div className="flex flex-wrap items-center gap-2"><span className="font-medium">{delivery.destinationName}</span><code className="text-xs text-[var(--muted)]" translate="no">{delivery.destinationKey}</code><StatusBadge value={delivery.status} />{delivery.required && <span className="text-xs text-[var(--muted)]">required</span>}</div><div className="mt-1 flex min-w-0 flex-wrap gap-x-3 gap-y-1 text-xs"><PublicationUrl label="Index" href={delivery.indexPublicUrl} /><PublicationUrl label="Pointer" href={delivery.pointerPublicUrl} /></div>{delivery.errorMessage && <p role="alert" className="mt-1 break-words text-sm text-[var(--danger)]"><code translate="no">{delivery.errorCode ?? "delivery.error"}</code>: {delivery.errorMessage}</p>}</div>)}{publication.deliveries.length === 0 && <p className="text-xs text-[var(--muted)]">No destination deliveries recorded.</p>}</div></article>)}</div>}</Panel.Body></Panel.Root>;
}

function PublicationUrl({ label, href }: { label: string; href: string | null }) {
  return href ? <a href={href} className="max-w-full truncate text-[var(--accent-strong)] hover:underline">{label}: {href}</a> : <span className="text-[var(--muted)]">{label}: —</span>;
}

function PublicationStageConsole({ environment, publishMode }: { environment: string; publishMode: "prod" | "dev" }) {
  const runStage = useRunPublicationStage();
  const [stage, setStage] = useState<PublicationStage>("artifactBuild");
  const [videoIds, setVideoIds] = useState("");
  const [artifactIds, setArtifactIds] = useState("");
  const [profileRevisionId, setProfileRevisionId] = useState("");
  const [destinationIds, setDestinationIds] = useState("");
  const [publicationId, setPublicationId] = useState("");
  const [result, setResult] = useState<PublicationStageResult | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const requiresProductionPointerConfirmation = publishMode === "prod" && stage === "pointerPublish";
  const pointerPublicationId = Number(publicationId);
  const pointerProfileRevisionId = Number(profileRevisionId);
  const pointerArtifactIds = parseIds(artifactIds);
  const hasValidPointerPublicationId = Number.isInteger(pointerPublicationId) && pointerPublicationId > 0;
  const hasValidPointerInputs = hasValidPointerPublicationId && pointerArtifactIds.length > 0 && Number.isInteger(pointerProfileRevisionId) && pointerProfileRevisionId > 0;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setValidationError(null);
    if (requiresProductionPointerConfirmation) {
      setValidationError("Review the production pointer publish in the confirmation dialog before running it.");
      return;
    }
    const parsedVideoIds = parseIds(videoIds); const parsedArtifactIds = parseIds(artifactIds); const parsedDestinationIds = parseIds(destinationIds);
    try {
      let next: PublicationStageResult;
      if (stage === "artifactBuild") {
        if (!parsedVideoIds.length) throw new Error("Enter at least 1 video ID to build artifacts.");
        next = await runStage.mutateAsync({ stage, body: { videoIds: parsedVideoIds, publishMode, environment, variant: "control", schemaVersion: 1, retryFailed: true, rerunSucceeded: false, includeNonEmbeddable: false } });
      } else if (stage === "pointerPublish") {
        const id = Number(publicationId);
        if (!Number.isInteger(id) || id < 1) throw new Error("Enter the publication ID before publishing its pointer.");
        const revisionId = Number(profileRevisionId);
        if (!parsedArtifactIds.length) throw new Error("Enter the artifact IDs included in this publication.");
        if (!Number.isInteger(revisionId) || revisionId < 1) throw new Error("Enter the publication profile revision ID used to build this publication.");
        next = await runStage.mutateAsync({ stage, body: { publicationId: id, artifactIds: parsedArtifactIds, profileRevisionId: revisionId, publishMode, environment, ...(parsedDestinationIds.length ? { destinationIds: parsedDestinationIds } : {}) } });
      } else {
        const revisionId = Number(profileRevisionId);
        if (!parsedArtifactIds.length) throw new Error("Enter artifact IDs produced by the artifact-build stage.");
        if (!Number.isInteger(revisionId) || revisionId < 1) throw new Error("Enter an active publication profile revision ID.");
        const body = { artifactIds: parsedArtifactIds, profileRevisionId: revisionId, publishMode, environment, ...(parsedDestinationIds.length ? { destinationIds: parsedDestinationIds } : {}) };
        next = stage === "publicationBuild"
          ? await runStage.mutateAsync({ stage, body: { ...body, schemaVersion: 1 } })
          : await runStage.mutateAsync({ stage, body });
      }
      setResult(next);
      if (next.artifactIds.length) setArtifactIds(next.artifactIds.join(", "));
      if (next.profileRevisionId) setProfileRevisionId(String(next.profileRevisionId));
      if (next.publicationId) setPublicationId(String(next.publicationId));
    } catch (error) { setValidationError(error instanceof Error ? error.message : "The stage could not be started."); }
  }

  async function confirmProductionPointerPublish() {
    setValidationError(null);
    const id = Number(publicationId);
    if (!Number.isInteger(id) || id < 1) throw new Error("Enter the publication ID before publishing its pointer.");
    const parsedArtifactIds = parseIds(artifactIds);
    if (!parsedArtifactIds.length) throw new Error("Enter the artifact IDs included in this publication.");
    const revisionId = Number(profileRevisionId);
    if (!Number.isInteger(revisionId) || revisionId < 1) throw new Error("Enter the publication profile revision ID used to build this publication.");
    const parsedDestinationIds = parseIds(destinationIds);
    const next = await runStage.mutateAsync({ stage: "pointerPublish", body: { publicationId: id, artifactIds: parsedArtifactIds, profileRevisionId: revisionId, publishMode, environment, ...(parsedDestinationIds.length ? { destinationIds: parsedDestinationIds } : {}) } });
    setResult(next);
    if (next.artifactIds.length) setArtifactIds(next.artifactIds.join(", "));
    if (next.profileRevisionId) setProfileRevisionId(String(next.profileRevisionId));
    if (next.publicationId) setPublicationId(String(next.publicationId));
  }

  const needsArtifacts = stage !== "artifactBuild";
  const usesDestinationIds = stage !== "artifactBuild";
  return <ActionDialog.Provider heading={`Publish production pointer for publication #${publicationId || "—"}`} description="This changes the production pointer. Review the publication membership and confirm the publication ID before publishing." confirmLabel="Publish production pointer" confirmationValue={hasValidPointerPublicationId ? String(pointerPublicationId) : undefined} tone="danger" onConfirm={confirmProductionPointerPublish}>
    <Panel.Root className="mb-4"><Panel.Header><Panel.HeadingGroup><Panel.Title>Stage Console</Panel.Title><Panel.Description>Artifact build accepts video IDs. Every routed stage accepts artifact IDs, profile revision, mode, environment, and optional destination IDs. Pointer publish additionally requires its publication ID.</Panel.Description></Panel.HeadingGroup></Panel.Header><Panel.Body><form className="grid gap-3 lg:grid-cols-2" onSubmit={submit}><label className="grid gap-1 text-sm font-medium">Stage<select value={stage} onChange={(event) => setStage(event.target.value as PublicationStage)} className={controlClass}>{(Object.keys(stageLabels) as PublicationStage[]).map((item) => <option key={item} value={item}>{stageLabels[item]}</option>)}</select></label>{stage === "artifactBuild" && <CsvField label="Video IDs" value={videoIds} onChange={setVideoIds} placeholder="12, 34, 56" required />}{needsArtifacts && <><CsvField label="Artifact IDs" value={artifactIds} onChange={setArtifactIds} placeholder="101, 102" required /><NumberField label="Profile revision ID" value={profileRevisionId} onChange={setProfileRevisionId} placeholder="24" required /></>}{stage === "pointerPublish" && <NumberField label="Publication ID" value={publicationId} onChange={setPublicationId} placeholder="88" required />}{usesDestinationIds && <CsvField label="Destination IDs (optional)" value={destinationIds} onChange={setDestinationIds} placeholder="3, 7" />}<div className="flex items-end">{requiresProductionPointerConfirmation ? <ActionDialog.Trigger><Button type="button" variant="destructive" disabled={runStage.isPending || !hasValidPointerInputs}>Review production pointer</Button></ActionDialog.Trigger> : <Button type="submit" variant="primary" disabled={runStage.isPending}>{runStage.isPending ? "Running stage…" : `Run ${stageLabels[stage]}`}</Button>}</div></form>{requiresProductionPointerConfirmation && !hasValidPointerInputs && <p className="mt-3 text-sm text-[var(--muted)]">Enter artifact IDs, an active profile revision ID, and a valid publication ID to review the production pointer publish.</p>}{(validationError || runStage.error) && <p className="mt-3 text-sm text-[var(--danger)]" role="alert">{validationError ?? runStage.error?.message}</p>}{result && <StageResult result={result} />}</Panel.Body></Panel.Root>
    {requiresProductionPointerConfirmation && <ActionDialog.Content><div className="rounded-md border bg-[var(--surface-muted)] p-3 text-sm"><p className="font-semibold">Production cutover</p><p className="mt-1 text-[var(--muted)]">Publication <code translate="no">#{publicationId}</code> with artifacts <code translate="no">{pointerArtifactIds.join(", ")}</code> from profile revision <code translate="no">#{profileRevisionId}</code> will become the active <code translate="no">{publishMode}/{environment}</code> pointer for the selected destinations.</p></div><ActionDialog.ConfirmationField /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content>}
  </ActionDialog.Provider>;
}

function StageResult({ result }: { result: PublicationStageResult }) {
  const stageLabel = stageLabels[result.stage as PublicationStage] ?? result.stage;
  return <div className="mt-4 grid gap-3 border-t pt-4" aria-live="polite"><div className="flex flex-wrap items-center gap-2"><p className="font-medium">Latest result: {stageLabel}</p><StatusBadge value={result.status} /><code className="text-xs text-[var(--muted)]" translate="no">artifacts {result.artifactIds.join(", ") || "—"} · publication {result.publicationId ?? "—"}</code></div>{result.missingPreconditions?.length ? <div role="alert" className="rounded-md border border-[var(--danger)] bg-[var(--danger-soft)] p-3 text-sm"><p className="font-semibold">Missing preconditions</p><ul className="mt-1 list-disc pl-5">{result.missingPreconditions.map((item, index) => <li key={index}>{JSON.stringify(item)}</li>)}</ul></div> : null}{result.destinationResults?.length ? <div className="grid gap-2">{result.destinationResults.map((destination) => <div key={`${destination.destinationType}-${destination.bindingId}`} className="rounded-md border p-3"><div className="flex flex-wrap items-center gap-2"><code translate="no">{destination.destinationType} #{destination.destinationId}</code><StatusBadge value={destination.status} />{destination.reused && <span className="text-xs text-[var(--muted)]">reused</span>}</div>{destination.publicUrl && <a className="mt-1 block truncate text-sm text-[var(--accent-strong)] hover:underline" href={destination.publicUrl}>{destination.publicUrl}</a>}{destination.errorMessage && <p role="alert" className="mt-1 break-words text-sm text-[var(--danger)]"><code translate="no">{destination.errorCode ?? "publication.error"}</code>: {destination.errorMessage}</p>}</div>)}</div> : null}</div>;
}

function CsvField({ label, value, onChange, placeholder, required = false }: { label: string; value: string; onChange: (value: string) => void; placeholder: string; required?: boolean }) { return <label className="grid gap-1 text-sm font-medium">{label}<input value={value} onChange={(event) => onChange(event.target.value)} required={required} inputMode="numeric" autoComplete="off" className={controlClass} placeholder={`${placeholder}…`} /></label>; }
function NumberField({ label, value, onChange, placeholder, required = false }: { label: string; value: string; onChange: (value: string) => void; placeholder: string; required?: boolean }) { return <label className="grid gap-1 text-sm font-medium">{label}<input value={value} onChange={(event) => onChange(event.target.value)} required={required} type="number" min="1" inputMode="numeric" autoComplete="off" className={controlClass} placeholder={`${placeholder}…`} /></label>; }
function parseIds(value: string) { return [...new Set(value.split(",").map((item) => Number(item.trim())).filter((item) => Number.isInteger(item) && item > 0))]; }
function parseFilterId(value: string | null) { const parsed = Number(value); return Number.isInteger(parsed) && parsed > 0 ? parsed : null; }
function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <Panel.Root><Panel.Body><p className="text-xs text-[var(--muted)]">{label}</p><p className="mt-1 text-xl font-semibold ops-number" translate="no">{value}</p><p className="mt-1 truncate text-xs text-[var(--muted)]" translate="no">{detail}</p></Panel.Body></Panel.Root>; }
