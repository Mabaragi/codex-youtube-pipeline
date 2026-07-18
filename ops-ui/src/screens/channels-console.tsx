"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { type FormEvent, useState } from "react";

import { ActionDialog } from "@/components/action-dialog";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import type { ChannelList, Streamer } from "@/features/catalog/api";
import { useChannels, useStreamers } from "@/features/catalog/api";
import { useCreateChannel, useCreateStreamer, useDeleteChannel, useDeleteStreamer, useUpdateChannel, useUpdateStreamer } from "@/features/configuration/api";
import { usePublishProfiles } from "@/features/publishing/api";
import { formatDateTime, formatNumber } from "@/lib/format";

type ChannelRow = ChannelList["items"][number];
const controlClass = "min-h-10 min-w-0 rounded-md border bg-[var(--surface)] px-3 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]";

export function ChannelsConsole({ initialChannels, initialStreamers }: { initialChannels: ChannelList | null; initialStreamers: Streamer[] | null }) {
  const channels = useChannels(initialChannels);
  const streamers = useStreamers(initialStreamers);
  const profiles = usePublishProfiles();
  const createStreamer = useCreateStreamer(); const updateStreamer = useUpdateStreamer(); const deleteStreamer = useDeleteStreamer();
  const createChannel = useCreateChannel(); const updateChannel = useUpdateChannel(); const deleteChannel = useDeleteChannel();
  const [editing, setEditing] = useState<ChannelRow | null>(null);
  const [newStreamerProfileId, setNewStreamerProfileId] = useState("");

  const columns: ColumnDef<ChannelRow>[] = [
    { header: "ID", accessorKey: "channelId", cell: ({ getValue }) => <code translate="no">#{String(getValue())}</code> },
    { header: "Channel", accessorKey: "name", cell: ({ row }) => <div className="min-w-0"><p className="font-medium">{row.original.name}</p><code className="text-xs text-[var(--muted)]" translate="no">{row.original.handle}</code></div> },
    { header: "Streamer", accessorKey: "streamerName", cell: ({ row }) => <span>{row.original.streamerName} <code translate="no">#{row.original.streamerId}</code></span> },
    { header: "Videos", accessorKey: "videoCount", cell: ({ getValue }) => <span className="ops-number">{formatNumber(Number(getValue()))}</span> },
    { header: "Work", accessorKey: "taskRunningCount", cell: ({ row }) => <span className="ops-number">running {row.original.taskRunningCount} · failed {row.original.taskFailedCount}</span> },
    { header: "Latest video", accessorKey: "latestVideoPublishedAt", cell: ({ getValue }) => <span className="ops-number whitespace-nowrap">{formatDateTime(String(getValue() ?? ""))}</span> },
    { header: "Actions", id: "actions", cell: ({ row }) => <div className="flex gap-2"><Button size="sm" onClick={() => setEditing(row.original)}>Edit</Button><ActionDialog.Provider heading={`Delete channel #${row.original.channelId}`} description={`Delete ${row.original.name}. Confirm the channel ID and provide a reason.`} confirmLabel="Delete" confirmationValue={String(row.original.channelId)} reasonRequired tone="danger" onConfirm={(reason) => deleteChannel.mutateAsync({ id: row.original.channelId, reason }).then(() => undefined)}><ActionDialog.Trigger><Button size="sm" variant="destructive">Delete</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ConfirmationField /><ActionDialog.ReasonField /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider></div> },
  ];

  function submitStreamer(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const formElement = event.currentTarget; const data = new FormData(formElement); void createStreamer.mutateAsync({ body: { name: String(data.get("name")), publishProfileId: Number(data.get("publishProfileId")) }, reason: String(data.get("reason")) }).then(() => { formElement.reset(); setNewStreamerProfileId(""); }).catch(() => undefined); }
  function submitChannel(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const formElement = event.currentTarget; const data = new FormData(formElement); void createChannel.mutateAsync({ streamerId: Number(data.get("streamerId")), body: { name: String(data.get("name")), handle: String(data.get("handle")), youtubeChannelId: String(data.get("youtubeChannelId")) || null } }).then(() => formElement.reset()).catch(() => undefined); }
  function saveChannel(event: FormEvent<HTMLFormElement>) { event.preventDefault(); if (!editing) return; const data = new FormData(event.currentTarget); void updateChannel.mutateAsync({ id: editing.channelId, body: { name: String(data.get("name")), handle: String(data.get("handle")), youtubeChannelId: String(data.get("youtubeChannelId")) || null } }).then(() => setEditing(null)).catch(() => undefined); }

  return <>
    <PageHeader eyebrow="Configuration" heading="Channels & Streamers" description="Every streamer must be assigned an active publication profile before channels can be collected." />
    <div className="mb-4 grid gap-4 xl:grid-cols-2">
      <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>Streamer Profiles</Panel.Title><Panel.Description>Assign a profile at creation and keep the selector available while data refreshes.</Panel.Description></Panel.HeadingGroup></Panel.Header><Panel.Body>
        <form onSubmit={submitStreamer} className="mb-4 grid gap-2 sm:grid-cols-2"><label className="sr-only" htmlFor="new-streamer-name">Streamer name</label><input id="new-streamer-name" name="name" required minLength={1} autoComplete="off" className={controlClass} placeholder="Streamer name…" /><label className="sr-only" htmlFor="new-streamer-profile">Publication profile</label><select id="new-streamer-profile" name="publishProfileId" required value={newStreamerProfileId} onChange={(event) => setNewStreamerProfileId(event.target.value)} disabled={!profiles.data?.length} className={controlClass}><option value="" disabled>{profiles.data?.length ? "Publication profile…" : "Create a profile first"}</option>{profiles.data?.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select><label className="sr-only" htmlFor="new-streamer-reason">Operator reason</label><input id="new-streamer-reason" name="reason" required minLength={3} maxLength={500} autoComplete="off" className={controlClass} placeholder="Operator reason…" /><Button type="submit" variant="primary" disabled={createStreamer.isPending || !profiles.data?.length}>{createStreamer.isPending ? "Creating…" : "Add Streamer"}</Button></form>
        {createStreamer.error && <p role="alert" className="mb-3 text-sm text-[var(--danger)]">{createStreamer.error.message}</p>}
        <div className="grid gap-2">{streamers.data?.map((streamer) => <div key={streamer.id} className="flex flex-wrap items-center gap-2 rounded-md border p-2"><form className="flex min-w-0 flex-1 flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); void updateStreamer.mutateAsync({ id: streamer.id, body: { name: String(data.get("name")), publishProfileId: Number(data.get("publishProfileId")) }, reason: String(data.get("reason")) }).catch(() => undefined); }}><code className="self-center" translate="no">#{streamer.id}</code><label className="sr-only" htmlFor={`streamer-${streamer.id}-name`}>Streamer name</label><input id={`streamer-${streamer.id}-name`} name="name" required defaultValue={streamer.name} autoComplete="off" className={`${controlClass} flex-1`} /><label className="sr-only" htmlFor={`streamer-${streamer.id}-profile`}>Publication profile</label><select id={`streamer-${streamer.id}-profile`} name="publishProfileId" required defaultValue={streamer.publishProfileId} disabled={!profiles.data?.length} className={`${controlClass} min-w-40`}>{profiles.data?.map((profile) => <option key={profile.id} value={profile.id}>{profile.name}</option>)}</select><label className="sr-only" htmlFor={`streamer-${streamer.id}-reason`}>Operator reason for {streamer.name}</label><input id={`streamer-${streamer.id}-reason`} name="reason" required minLength={3} maxLength={500} autoComplete="off" className={`${controlClass} min-w-48 flex-1`} placeholder="Operator reason…" /><Button type="submit" disabled={updateStreamer.isPending}>Save</Button></form><ActionDialog.Provider heading={`Delete streamer #${streamer.id}`} description={`Delete ${streamer.name} and linked channel relationships.`} confirmLabel="Delete" confirmationValue={String(streamer.id)} reasonRequired tone="danger" onConfirm={(reason) => deleteStreamer.mutateAsync({ id: streamer.id, reason }).then(() => undefined)}><ActionDialog.Trigger><Button variant="destructive">Delete</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ConfirmationField /><ActionDialog.ReasonField /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider></div>)}</div>
      </Panel.Body></Panel.Root>
      <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>{editing ? `Edit Channel #${editing.channelId}` : "Add Channel"}</Panel.Title><Panel.Description>Choose a streamer that already has a publication profile.</Panel.Description></Panel.HeadingGroup></Panel.Header><Panel.Body><form onSubmit={editing ? saveChannel : submitChannel} className="grid gap-3 sm:grid-cols-2"><label className="grid gap-1 text-sm font-medium">Streamer<select name="streamerId" disabled={Boolean(editing)} required defaultValue={editing?.streamerId ?? ""} className={controlClass}><option value="" disabled>Select a streamer…</option>{streamers.data?.map((streamer) => <option key={streamer.id} value={streamer.id}>{streamer.name}</option>)}</select></label><Field name="name" label="Name" defaultValue={editing?.name} /><Field name="handle" label="Handle" defaultValue={editing?.handle} /><Field name="youtubeChannelId" label="YouTube channel ID" defaultValue={editing?.youtubeChannelId ?? ""} required={false} /><div className="flex gap-2 sm:col-span-2"><Button type="submit" variant="primary" disabled={createChannel.isPending || updateChannel.isPending}>{editing ? "Save Channel" : "Add Channel"}</Button>{editing && <Button type="button" onClick={() => setEditing(null)}>Cancel</Button>}</div></form></Panel.Body></Panel.Root>
    </div>
    <DataTable.Provider rows={channels.data?.items ?? []} columns={columns} getRowId={(row) => String(row.channelId)} state={{ initialLoading: channels.isLoading, refreshing: channels.isFetching && !channels.isLoading, placeholder: channels.isPlaceholderData, error: channels.error?.message ?? null }} meta={{ label: "Channel list", emptyTitle: "No channels registered", emptyDescription: "Create a streamer and assign a publication profile first." }}><DataTable.Frame><DataTable.Toolbar><span className="text-sm text-[var(--muted)]">{formatNumber(channels.data?.items.length)} channels</span></DataTable.Toolbar><DataTable.Content /></DataTable.Frame></DataTable.Provider>
  </>;
}

function Field({ name, label, defaultValue = "", required = true }: { name: string; label: string; defaultValue?: string; required?: boolean }) {
  return <label className="grid gap-1 text-sm font-medium">{label}<input name={name} required={required} defaultValue={defaultValue} autoComplete="off" className={controlClass} placeholder={`${label}…`} /></label>;
}
