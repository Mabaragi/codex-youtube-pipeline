"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import type { UsageList } from "@/features/observability/api";
import { useUsage } from "@/features/observability/api";
import { formatDateTime, formatNumber } from "@/lib/format";

type UsageRow = UsageList["items"][number];
const columns: ColumnDef<UsageRow>[] = [
  { header: "ID", accessorKey: "codexUsageId", cell: ({ getValue }) => <code translate="no">#{String(getValue())}</code> },
  { header: "시각", accessorKey: "createdAt", cell: ({ getValue }) => <span className="ops-number whitespace-nowrap">{formatDateTime(String(getValue()))}</span> },
  { header: "Operation", accessorKey: "operation", cell: ({ getValue }) => <code translate="no">{String(getValue())}</code> },
  { header: "Model", accessorKey: "model", cell: ({ row }) => <span className="font-mono" translate="no">{row.original.model ?? "—"} / {row.original.reasoningEffort ?? "—"}</span> },
  { header: "상태", accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={String(getValue())} /> },
  { header: "Tokens", accessorKey: "totalTokens", cell: ({ getValue }) => <span className="ops-number">{formatNumber(Number(getValue() ?? 0))}</span> },
  { header: "Duration", accessorKey: "durationMs", cell: ({ getValue }) => <span className="ops-number">{formatNumber(Number(getValue()))}ms</span> },
  { header: "Video", accessorKey: "videoId", cell: ({ row }) => row.original.videoId ? <Link href={`/content/videos/${row.original.videoId}`} className="font-mono hover:underline">#{row.original.videoId}</Link> : "—" },
];

export function UsageConsole({ initialData }: { initialData: UsageList | null }) {
  const router = useRouter(); const pathname = usePathname(); const params = useSearchParams(); const model = params.get("model") ?? undefined; const status = params.get("status") ?? undefined; const cursor = Number(params.get("cursor")) || undefined; const query = useUsage({ model, status, cursor }, initialData); const summary = query.data?.summary;
  function replace(values: Record<string, string | undefined>) { const next = new URLSearchParams(params); Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key)); router.replace(`${pathname}?${next.toString()}`, { scroll: false }); }
  return <><PageHeader eyebrow="관측" heading="Codex usage" description="로그인이나 임의 prompt 실행 없이, 실제 파이프라인 호출의 token·시간·실패만 집계합니다." /><div className="mb-4 grid gap-4 sm:grid-cols-2 xl:grid-cols-4"><Metric label="runs" value={summary?.runCount} /><Metric label="total tokens" value={summary?.totalTokens} /><Metric label="input" value={summary?.inputTokens} /><Metric label="reasoning output" value={summary?.reasoningOutputTokens} /></div><DataTable.Provider rows={query.data?.items ?? []} columns={columns} getRowId={(row) => String(row.codexUsageId)} state={{ initialLoading: query.isLoading, refreshing: query.isFetching && !query.isLoading, placeholder: query.isPlaceholderData, error: query.error?.message ?? null }} actions={{ previous: () => replace({ cursor: undefined }), next: () => replace({ cursor: String(query.data?.nextCursor) }) }} meta={{ label: "Codex usage 목록", emptyTitle: "사용량 기록이 없습니다.", emptyDescription: "Codex 기반 작업이 실행되면 기록됩니다.", canPrevious: Boolean(cursor), canNext: Boolean(query.data?.nextCursor) }}><DataTable.Frame><DataTable.Toolbar><label className="grid gap-1 text-xs font-medium">Model<input value={model ?? ""} onChange={(event) => replace({ model: event.target.value || undefined, cursor: undefined })} className="min-h-10 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" /></label><label className="grid gap-1 text-xs font-medium">상태<select value={status ?? ""} onChange={(event) => replace({ status: event.target.value || undefined, cursor: undefined })} className="min-h-10 rounded-md border bg-[var(--surface)] px-3 text-sm"><option value="">전체</option><option value="succeeded">succeeded</option><option value="failed">failed</option></select></label></DataTable.Toolbar><DataTable.Content /><DataTable.Pagination /></DataTable.Frame></DataTable.Provider></>;
}

function Metric({ label, value }: { label: string; value: number | undefined }) { return <Panel.Root><Panel.Body><p className="text-xs text-[var(--muted)]" translate="no">{label}</p><p className="mt-1 text-2xl font-semibold ops-number">{formatNumber(value)}</p></Panel.Body></Panel.Root>; }
