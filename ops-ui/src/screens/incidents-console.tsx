"use client";

import type { ColumnDef } from "@tanstack/react-table";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import type { IncidentList } from "@/features/automation/api";
import { useIncidents } from "@/features/automation/api";
import { formatDateTime } from "@/lib/format";

type IncidentRow = IncidentList["items"][number];

const columns: ColumnDef<IncidentRow>[] = [
  { header: "ID", accessorKey: "id", cell: ({ row }) => <Link href={`/incidents/${row.original.id}`} className="font-mono font-semibold text-[var(--accent-strong)] hover:underline">#{row.original.id}</Link> },
  { header: "심각도", accessorKey: "severity", cell: ({ getValue }) => <StatusBadge value={String(getValue())} /> },
  { header: "상태", accessorKey: "state", cell: ({ getValue }) => <StatusBadge value={String(getValue())} /> },
  { header: "유형", accessorKey: "incidentType", cell: ({ getValue }) => <code translate="no">{String(getValue())}</code> },
  { header: "오류", accessorKey: "errorType", cell: ({ row }) => <span className="block max-w-72 truncate" title={row.original.errorMessage ?? undefined} translate="no">{row.original.errorType ?? "—"}</span> },
  { header: "대상", accessorKey: "workItemId", cell: ({ row }) => <span className="font-mono" translate="no">{row.original.workItemId ? `work:${row.original.workItemId}` : row.original.workflowRunId ? `workflow:${row.original.workflowRunId}` : "—"}</span> },
  { header: "발생", accessorKey: "occurrenceCount", cell: ({ getValue }) => <span className="ops-number">{String(getValue())}</span> },
  { header: "최근 감지", accessorKey: "lastSeenAt", cell: ({ getValue }) => <span className="ops-number whitespace-nowrap">{formatDateTime(String(getValue()))}</span> },
];

export function IncidentsConsole({ initialData }: { initialData: IncidentList | null }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const state = (searchParams.get("state") ?? "open") as "open" | "acknowledged" | "resolved" | "suppressed";
  const query = useIncidents({ state, limit: 100 }, initialData);
  function changeState(value: string) {
    const next = new URLSearchParams(searchParams);
    next.set("state", value);
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }
  return <>
    <PageHeader eyebrow="복구 관제" heading="Incidents" description="supervisor가 중복 제거한 예외 사건만 확인하고, 검증된 안전 조치를 실행합니다." />
    <DataTable.Provider rows={query.data?.items ?? []} columns={columns} getRowId={(row) => String(row.id)} state={{ initialLoading: query.isLoading, refreshing: query.isFetching && !query.isLoading, placeholder: query.isPlaceholderData, error: query.error?.message ?? null }} meta={{ label: "Incident 목록", emptyTitle: "해당 상태의 Incident가 없습니다.", emptyDescription: "파이프라인이 정상이라면 열린 사건이 없는 것이 정상입니다." }}>
      <DataTable.Frame><DataTable.Toolbar><label className="grid gap-1 text-xs font-medium" htmlFor="incident-state">상태<select id="incident-state" value={state} onChange={(event) => changeState(event.target.value)} className="min-h-10 rounded-md border bg-[var(--surface)] px-3 text-sm"><option value="open">open</option><option value="acknowledged">acknowledged</option><option value="resolved">resolved</option><option value="suppressed">suppressed</option></select></label></DataTable.Toolbar><DataTable.Content /></DataTable.Frame>
    </DataTable.Provider>
  </>;
}
