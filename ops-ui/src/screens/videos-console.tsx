"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { VideoList } from "@/features/content/api";
import { useVideos } from "@/features/content/api";
import { formatDateTime } from "@/lib/format";

type VideoRow = VideoList["items"][number];
const columns: ColumnDef<VideoRow>[] = [
  { header: "ID", accessorKey: "videoId", cell: ({ row }) => <Link href={`/content/videos/${row.original.videoId}`} className="font-mono font-semibold text-[var(--accent-strong)] hover:underline">#{row.original.videoId}</Link> },
  { header: "영상", accessorKey: "title", cell: ({ row }) => <div className="min-w-64"><p className="line-clamp-2 font-medium">{row.original.title}</p><p className="mt-1 font-mono text-xs text-[var(--muted)]" translate="no">{row.original.youtubeVideoId}</p></div> },
  { header: "채널", accessorKey: "channelName" },
  { header: "자막", accessorKey: "transcriptId", cell: ({ row }) => row.original.transcriptId ? <Link href={`/content/transcripts/${row.original.transcriptId}`} className="font-mono hover:underline">#{row.original.transcriptId}</Link> : "—" },
  { header: "생성", accessorKey: "generation", cell: ({ row }) => <div className="grid gap-1 text-xs"><StatusBadge value={row.original.generation.microEvents.latestTaskStatus ?? (row.original.generation.microEvents.generated ? "succeeded" : "none")} /><StatusBadge value={row.original.generation.timeline.latestTaskStatus ?? (row.original.generation.timeline.generated ? "succeeded" : "none")} /></div> },
  { header: "최근 작업", accessorKey: "latestTaskStatus", cell: ({ row }) => <StatusBadge value={row.original.latestTaskStatus ?? "none"} /> },
  { header: "공개", accessorKey: "publishedAt", cell: ({ getValue }) => <span className="whitespace-nowrap ops-number">{formatDateTime(String(getValue()))}</span> },
];

export function VideosConsole({ initialData }: { initialData: VideoList | null }) {
  const router = useRouter(); const pathname = usePathname(); const searchParams = useSearchParams();
  const search = searchParams.get("search") ?? ""; const offset = Number(searchParams.get("offset")) || 0; const channelId = Number(searchParams.get("channelId")) || undefined;
  const [draft, setDraft] = useState(search);
  const query = useVideos({ search: search || undefined, channelId, limit: 50, offset }, initialData);
  function replace(values: Record<string, string | undefined>) { const next = new URLSearchParams(searchParams); Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key)); router.replace(`${pathname}?${next.toString()}`, { scroll: false }); }
  function submit(event: FormEvent) { event.preventDefault(); replace({ search: draft || undefined, offset: undefined }); }
  return <><PageHeader eyebrow="콘텐츠" heading="영상" description="수집된 영상과 자막·마이크로 이벤트·타임라인 생성 단계를 함께 조회합니다." /><DataTable.Provider rows={query.data?.items ?? []} columns={columns} getRowId={(row) => String(row.videoId)} state={{ initialLoading: query.isLoading, refreshing: query.isFetching && !query.isLoading, placeholder: query.isPlaceholderData, error: query.error?.message ?? null }} actions={{ previous: () => replace({ offset: String(Math.max(0, offset - 50)) }), next: () => replace({ offset: String(offset + 50) }) }} meta={{ label: "영상 목록", emptyTitle: "조건에 맞는 영상이 없습니다.", emptyDescription: "검색어 또는 채널 필터를 바꿔 보세요.", canPrevious: offset > 0, canNext: offset + 50 < (query.data?.total ?? 0) }}><DataTable.Frame><DataTable.Toolbar><form onSubmit={submit} className="flex flex-wrap items-end gap-2"><label className="grid gap-1 text-xs font-medium" htmlFor="video-search">검색<input id="video-search" name="search" autoComplete="off" value={draft} onChange={(event) => setDraft(event.target.value)} className="min-h-10 min-w-64 rounded-md border bg-[var(--surface)] px-3 text-sm" placeholder="제목 또는 YouTube ID" /></label><label className="grid gap-1 text-xs font-medium" htmlFor="video-channel">채널 ID<input id="video-channel" name="channelId" inputMode="numeric" defaultValue={channelId} className="min-h-10 w-28 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" /></label><Button type="submit">적용</Button></form></DataTable.Toolbar><DataTable.Content /><DataTable.Pagination /></DataTable.Frame></DataTable.Provider></>;
}
