"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { ActionDialog } from "@/components/action-dialog";
import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import type { ArchiveCurrent, ArchiveVideos } from "@/features/publishing/api";
import { useArchiveCurrent, useArchiveVideos, usePublishVideo } from "@/features/publishing/api";
import { formatDateTime, formatNumber } from "@/lib/format";

type ArchiveRow = ArchiveVideos["items"][number];

export function PublishingConsole({ initialCurrent, initialVideos }: { initialCurrent: ArchiveCurrent | null; initialVideos: ArchiveVideos | null }) {
  const router = useRouter(); const pathname = usePathname(); const params = useSearchParams();
  const publishMode = params.get("mode") === "dev" ? "dev" : "prod"; const environment = params.get("environment") ?? (publishMode === "prod" ? "prod" : "dev"); const offset = Number(params.get("offset")) || 0;
  const current = useArchiveCurrent({ environment, publishMode, offset }, initialCurrent); const videos = useArchiveVideos({ environment, publishMode, offset }, initialVideos); const publish = usePublishVideo(environment, publishMode);
  function replace(values: Record<string, string | undefined>) { const next = new URLSearchParams(params); Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key)); router.replace(`${pathname}?${next.toString()}`, { scroll: false }); }
  const columns: ColumnDef<ArchiveRow>[] = [
    { header: "영상", accessorKey: "title", cell: ({ row }) => <div><Link href={`/content/videos/${row.original.videoId}`} className="font-medium hover:underline">{row.original.title}</Link><p className="font-mono text-xs text-[var(--muted)]">#{row.original.videoId} · {row.original.youtubeVideoId}</p></div> },
    { header: "타임라인", accessorKey: "timelineReady", cell: ({ row }) => <StatusBadge value={row.original.timelineReady ? "ready" : "not_ready"} /> },
    { header: "에피소드", accessorKey: "timelineEpisodeCount", cell: ({ getValue }) => <span className="ops-number">{String(getValue())}</span> },
    { header: "Publish", accessorKey: "latestTask", cell: ({ row }) => <StatusBadge value={row.original.latestTask?.status ?? (row.original.latestArtifact ? "published" : "not_ready")} /> },
    { header: "최근 아티팩트", accessorKey: "latestArtifact", cell: ({ row }) => <span className="ops-number whitespace-nowrap">{formatDateTime(row.original.latestArtifact?.createdAt)}</span> },
    { header: "조작", id: "actions", cell: ({ row }) => <ActionDialog.Provider heading={`${publishMode}/${environment} 퍼블리시`} description={`영상 #${row.original.videoId}의 검증된 최신 타임라인을 control variant, schemaVersion 1로 발행합니다.`} confirmLabel="퍼블리시" confirmationValue={String(row.original.videoId)} onConfirm={async () => { await publish.mutateAsync(row.original.videoId); }}><ActionDialog.Trigger><Button size="sm" disabled={!row.original.timelineReady || publish.isPending}>퍼블리시</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ConfirmationField /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider> },
  ];
  const publication = current.data?.latestPublication;
  return <><PageHeader eyebrow="배포" heading="Publishing" description="prod/dev archive publication과 영상별 최신 타임라인 발행 상태를 관리합니다." actions={<div className="flex gap-2"><select aria-label="Publish mode" value={publishMode} onChange={(event) => replace({ mode: event.target.value, environment: event.target.value, offset: undefined })} className="min-h-10 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm"><option value="prod">prod</option><option value="dev">dev</option></select><input aria-label="Environment" value={environment} onChange={(event) => replace({ environment: event.target.value, offset: undefined })} className="min-h-10 w-28 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" /></div>} />
    <div className="mb-4 grid gap-4 md:grid-cols-3"><Metric label="publication" value={publication ? `#${publication.publicationId}` : "없음"} detail={publication ? formatDateTime(publication.createdAt) : `${environment}/${publishMode}`} /><Metric label="videos" value={formatNumber(publication?.videoCount)} detail={publication?.version ?? "—"} /><Metric label="storage" value={current.data?.storage.configured ? "connected" : "disabled"} detail={current.data?.storage.bucket ?? "—"} /></div>
    <DataTable.Provider rows={videos.data?.items ?? []} columns={columns} getRowId={(row) => String(row.videoId)} state={{ initialLoading: videos.isLoading, refreshing: videos.isFetching && !videos.isLoading, placeholder: videos.isPlaceholderData, error: videos.error?.message ?? null }} actions={{ previous: () => replace({ offset: String(Math.max(0, offset - 50)) }), next: () => replace({ offset: String(offset + 50) }) }} meta={{ label: "Archive 영상 목록", emptyTitle: "발행 가능한 영상이 없습니다.", emptyDescription: "타임라인 생성 상태를 확인하세요.", canPrevious: offset > 0, canNext: offset + 50 < (videos.data?.total ?? 0) }}><DataTable.Frame><DataTable.Toolbar><span className="text-sm text-[var(--muted)]">총 {formatNumber(videos.data?.total)}개</span></DataTable.Toolbar><DataTable.Content /><DataTable.Pagination /></DataTable.Frame></DataTable.Provider>
  </>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <Panel.Root><Panel.Body><p className="text-xs text-[var(--muted)]" translate="no">{label}</p><p className="mt-1 text-xl font-semibold ops-number" translate="no">{value}</p><p className="mt-1 truncate text-xs text-[var(--muted)]" translate="no">{detail}</p></Panel.Body></Panel.Root>; }
