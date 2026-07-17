"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Transcript } from "@/features/content/api";
import { useTranscripts } from "@/features/content/api";
import { formatDateTime } from "@/lib/format";

const columns: ColumnDef<Transcript>[] = [
  { header: "ID", accessorKey: "id", cell: ({ row }) => <Link href={`/content/transcripts/${row.original.id}`} className="font-mono font-semibold text-[var(--accent-strong)] hover:underline">#{row.original.id}</Link> },
  { header: "YouTube video", accessorKey: "videoId", cell: ({ getValue }) => <code translate="no">{String(getValue())}</code> },
  { header: "언어", accessorKey: "language", cell: ({ row }) => <span>{row.original.language} <code translate="no">({row.original.languageCode})</code></span> },
  { header: "출처", accessorKey: "isGenerated", cell: ({ row }) => <StatusBadge value={row.original.isGenerated ? "asr" : "youtube"} /> },
  { header: "segments", accessorKey: "segmentCount", cell: ({ getValue }) => <span className="ops-number">{String(getValue())}</span> },
  { header: "text", accessorKey: "textLength", cell: ({ getValue }) => <span className="ops-number">{String(getValue())}</span> },
  { header: "갱신", accessorKey: "updatedAt", cell: ({ getValue }) => <span className="ops-number whitespace-nowrap">{formatDateTime(String(getValue()))}</span> },
];

export function TranscriptsConsole({ initialData }: { initialData: Transcript[] | null }) {
  const router = useRouter(); const pathname = usePathname(); const searchParams = useSearchParams();
  const videoId = searchParams.get("videoId") ?? ""; const languageCode = searchParams.get("languageCode") ?? ""; const offset = Number(searchParams.get("offset")) || 0;
  const [videoDraft, setVideoDraft] = useState(videoId); const [languageDraft, setLanguageDraft] = useState(languageCode);
  const query = useTranscripts({ videoId: videoId || undefined, languageCode: languageCode || undefined, limit: 50, offset }, initialData);
  function replace(values: Record<string, string | undefined>) { const next = new URLSearchParams(searchParams); Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key)); router.replace(`${pathname}?${next.toString()}`, { scroll: false }); }
  function submit(event: FormEvent) { event.preventDefault(); replace({ videoId: videoDraft || undefined, languageCode: languageDraft || undefined, offset: undefined }); }
  return <><PageHeader eyebrow="콘텐츠" heading="자막" description="YouTube 자막과 ASR 결과, cue 생성에 사용된 저장 아티팩트를 조회합니다." /><DataTable.Provider rows={query.data ?? []} columns={columns} getRowId={(row) => String(row.id)} state={{ initialLoading: query.isLoading, refreshing: query.isFetching && !query.isLoading, placeholder: query.isPlaceholderData, error: query.error?.message ?? null }} actions={{ previous: () => replace({ offset: String(Math.max(0, offset - 50)) }), next: () => replace({ offset: String(offset + 50) }) }} meta={{ label: "자막 목록", emptyTitle: "자막이 없습니다.", emptyDescription: "필터를 바꾸거나 자막 수집 작업을 실행하세요.", canPrevious: offset > 0, canNext: (query.data?.length ?? 0) === 50 }}><DataTable.Frame><DataTable.Toolbar><form className="flex flex-wrap items-end gap-2" onSubmit={submit}><label className="grid gap-1 text-xs font-medium" htmlFor="transcript-video">YouTube video ID<input id="transcript-video" value={videoDraft} onChange={(event) => setVideoDraft(event.target.value)} autoComplete="off" className="min-h-10 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" /></label><label className="grid gap-1 text-xs font-medium" htmlFor="transcript-language">언어 코드<input id="transcript-language" value={languageDraft} onChange={(event) => setLanguageDraft(event.target.value)} autoComplete="off" className="min-h-10 w-28 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" placeholder="ko" /></label><Button type="submit">적용</Button></form></DataTable.Toolbar><DataTable.Content /><DataTable.Pagination /></DataTable.Frame></DataTable.Provider></>;
}
