"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import type { EventList } from "@/features/observability/api";
import { useEvents } from "@/features/observability/api";
import { formatDateTime } from "@/lib/format";

type EventRow = EventList["items"][number];
const columns: ColumnDef<EventRow>[] = [
  { header: "ID", accessorKey: "eventId", cell: ({ getValue }) => <code translate="no">#{String(getValue())}</code> },
  { header: "시각", accessorKey: "occurredAt", cell: ({ getValue }) => <span className="ops-number whitespace-nowrap">{formatDateTime(String(getValue()))}</span> },
  { header: "심각도", accessorKey: "severity", cell: ({ getValue }) => <StatusBadge value={String(getValue())} /> },
  { header: "Event", accessorKey: "eventType", cell: ({ getValue }) => <code translate="no">{String(getValue())}</code> },
  { header: "메시지", accessorKey: "message", cell: ({ row }) => <span className="block max-w-96 truncate" title={row.original.message}>{row.original.message}</span> },
  { header: "대상", accessorKey: "subjectId", cell: ({ row }) => row.original.subjectType ? <span className="font-mono" translate="no">{row.original.subjectType}:{row.original.subjectId}</span> : "—" },
  { header: "Work", accessorKey: "workItemId", cell: ({ row }) => row.original.workItemId ? <Link href={`/executions/work-items/${row.original.workItemId}`} className="font-mono hover:underline">#{row.original.workItemId}</Link> : "—" },
  { header: "오류", accessorKey: "errorType", cell: ({ row }) => <code className="text-[var(--danger)]" translate="no">{row.original.errorType ?? "—"}</code> },
];

export function EventsConsole({ initialData }: { initialData: EventList | null }) {
  const router = useRouter(); const pathname = usePathname(); const params = useSearchParams(); const severity = params.get("severity") ?? undefined; const eventType = params.get("eventType") ?? undefined; const cursor = Number(params.get("cursor")) || undefined; const query = useEvents({ severity, eventType, cursor }, initialData);
  function replace(values: Record<string, string | undefined>) { const next = new URLSearchParams(params); Object.entries(values).forEach(([key, value]) => value ? next.set(key, value) : next.delete(key)); router.replace(`${pathname}?${next.toString()}`, { scroll: false }); }
  return <><PageHeader eyebrow="관측" heading="Operation events" description="작업, 외부 API, 운영자 변경과 오류를 하나의 감사 이벤트 스트림으로 조회합니다." /><DataTable.Provider rows={query.data?.items ?? []} columns={columns} getRowId={(row) => String(row.eventId)} state={{ initialLoading: query.isLoading, refreshing: query.isFetching && !query.isLoading, placeholder: query.isPlaceholderData, error: query.error?.message ?? null }} actions={{ previous: () => replace({ cursor: undefined }), next: () => replace({ cursor: String(query.data?.nextCursor) }) }} meta={{ label: "운영 이벤트 목록", emptyTitle: "이벤트가 없습니다.", emptyDescription: "필터를 바꾸거나 작업 실행 후 다시 확인하세요.", canPrevious: Boolean(cursor), canNext: Boolean(query.data?.nextCursor) }}><DataTable.Frame><DataTable.Toolbar><label className="grid gap-1 text-xs font-medium">심각도<select value={severity ?? ""} onChange={(event) => replace({ severity: event.target.value || undefined, cursor: undefined })} className="min-h-10 rounded-md border bg-[var(--surface)] px-3 text-sm"><option value="">전체</option><option value="info">info</option><option value="warning">warning</option><option value="error">error</option></select></label><label className="grid gap-1 text-xs font-medium">Event type<input value={eventType ?? ""} onChange={(event) => replace({ eventType: event.target.value || undefined, cursor: undefined })} className="min-h-10 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" /></label></DataTable.Toolbar><DataTable.Content /><DataTable.Pagination /></DataTable.Frame></DataTable.Provider></>;
}
