"use client";

import * as Tabs from "@radix-ui/react-tabs";
import type { ColumnDef } from "@tanstack/react-table";
import { Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState } from "react";

import { DataTable } from "@/components/data-table";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { BatchList, WorkflowList, WorkItemList } from "@/features/work/api";
import { useBatches, useWorkflows, useWorkItems } from "@/features/work/api";
import { formatDateTime } from "@/lib/format";

type WorkflowRow = WorkflowList["items"][number];
type BatchRow = BatchList["items"][number];
type WorkRow = WorkItemList["items"][number];

const WORKFLOW_COLUMNS: ColumnDef<WorkflowRow>[] = [
  { header: "ID", accessorKey: "id", cell: ({ row }) => <Link className="font-mono font-semibold text-[var(--accent-strong)] hover:underline" href={`/executions/workflows/${row.original.id}`}>#{row.original.id}</Link> },
  { header: "Video", accessorKey: "videoId", cell: ({ row }) => <Link className="font-mono hover:underline" href={`/content/videos/${row.original.videoId}`}>{row.original.videoId}</Link> },
  { header: "Workflow", accessorKey: "workflowType", cell: ({ getValue }) => <code translate="no">{String(getValue())}</code> },
  { header: "Stage", accessorKey: "currentStage", cell: ({ row }) => <span translate="no">{row.original.currentStage ?? row.original.waitingReason ?? "—"}</span> },
  { header: "상태", accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={String(getValue())} /> },
  { header: "오류", accessorKey: "errorCode", cell: ({ row }) => <span className="block max-w-64 truncate text-[var(--danger)]" title={row.original.errorMessage ?? undefined} translate="no">{row.original.errorCode ?? "—"}</span> },
  { header: "갱신", accessorKey: "updatedAt", cell: ({ getValue }) => <span className="ops-number whitespace-nowrap">{formatDateTime(String(getValue()))}</span> },
];

const BATCH_COLUMNS: ColumnDef<BatchRow>[] = [
  { header: "ID", accessorKey: "id", cell: ({ row }) => <Link className="font-mono font-semibold text-[var(--accent-strong)] hover:underline" href={`/executions/batches/${row.original.id}`}>#{row.original.id}</Link> },
  { header: "Operation", accessorKey: "operationType", cell: ({ getValue }) => <code translate="no">{String(getValue())}</code> },
  { header: "상태", accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={String(getValue())} /> },
  { header: "Actor", accessorKey: "actorType", cell: ({ getValue }) => <span translate="no">{String(getValue())}</span> },
  { header: "요청", accessorKey: "requestedCount", cell: ({ getValue }) => <span className="ops-number">{String(getValue())}</span> },
  { header: "생성", accessorKey: "createdAt", cell: ({ getValue }) => <span className="ops-number whitespace-nowrap">{formatDateTime(String(getValue()))}</span> },
  { header: "완료", accessorKey: "completedAt", cell: ({ row }) => <span className="ops-number whitespace-nowrap">{formatDateTime(row.original.completedAt)}</span> },
];

const WORK_COLUMNS: ColumnDef<WorkRow>[] = [
  { header: "ID", accessorKey: "id", cell: ({ row }) => <Link className="font-mono font-semibold text-[var(--accent-strong)] hover:underline" href={`/executions/work-items/${row.original.id}`}>#{row.original.id}</Link> },
  { header: "Task", accessorKey: "taskType", cell: ({ getValue }) => <code translate="no">{String(getValue())}</code> },
  { header: "대상", accessorKey: "subjectId", cell: ({ row }) => <span translate="no">{row.original.subjectType}:{row.original.subjectId ?? "—"}</span> },
  { header: "상태", accessorKey: "status", cell: ({ getValue }) => <StatusBadge value={String(getValue())} /> },
  { header: "Outcome", accessorKey: "outcomeCode", cell: ({ getValue }) => <span translate="no">{String(getValue() ?? "—")}</span> },
  { header: "오류", accessorKey: "errorCode", cell: ({ row }) => <span className="block max-w-64 truncate text-[var(--danger)]" title={row.original.errorMessage ?? undefined} translate="no">{row.original.errorCode ?? "—"}</span> },
  { header: "갱신", accessorKey: "updatedAt", cell: ({ getValue }) => <span className="ops-number whitespace-nowrap">{formatDateTime(String(getValue()))}</span> },
];

export function ExecutionsConsole({ initialWorkflows, initialBatches, initialWork }: { initialWorkflows: WorkflowList | null; initialBatches: BatchList | null; initialWork: WorkItemList | null }) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const tab = searchParams.get("tab") ?? "workflows";
  const status = searchParams.get("status") ?? undefined;
  const cursor = Number(searchParams.get("cursor")) || undefined;
  const [filterValue, setFilterValue] = useState(status ?? "");
  const workflows = useWorkflows({ status, cursor, limit: 50 }, initialWorkflows);
  const batches = useBatches({ status, cursor, limit: 50 }, initialBatches);
  const work = useWorkItems({ status, cursor, limit: 50 }, initialWork);

  function updateUrl(values: Record<string, string | undefined>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(values)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    router.replace(`${pathname}?${next.toString()}`, { scroll: false });
  }

  function submitFilter(event: FormEvent) { event.preventDefault(); updateUrl({ status: filterValue || undefined, cursor: undefined }); }
  const filter = <form className="flex min-w-0 flex-wrap items-end gap-2" onSubmit={submitFilter}><label className="grid min-w-48 gap-1 text-xs font-medium" htmlFor="execution-status">상태 필터<input id="execution-status" name="status" autoComplete="off" placeholder="running, failed…" value={filterValue} onChange={(event) => setFilterValue(event.target.value)} className="min-h-9 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" /></label><Button type="submit" size="sm"><Search aria-hidden="true" />적용</Button></form>;

  return <><PageHeader eyebrow="실행 추적" heading="Work · Workflow · Batch" description="모든 실행 단위를 같은 cursor·필터 규칙으로 탐색하고 상세 provenance와 attempt를 확인합니다." /><Tabs.Root value={tab} onValueChange={(value) => updateUrl({ tab: value, cursor: undefined })}><Tabs.List aria-label="실행 유형" className="flex min-h-11 w-fit gap-1 rounded-md border bg-[var(--surface)] p-1"><TabTrigger value="workflows">Workflow</TabTrigger><TabTrigger value="batches">Batch</TabTrigger><TabTrigger value="work">Work item</TabTrigger></Tabs.List><Tabs.Content value="workflows" className="mt-4"><DataTable.Provider rows={workflows.data?.items ?? []} columns={WORKFLOW_COLUMNS} getRowId={(row) => String(row.id)} state={{ initialLoading: workflows.isLoading, refreshing: workflows.isFetching && !workflows.isLoading, placeholder: workflows.isPlaceholderData, error: workflows.error?.message ?? null }} actions={{ next: () => updateUrl({ cursor: String(workflows.data?.nextCursor) }), previous: () => updateUrl({ cursor: undefined }) }} meta={{ label: "Workflow 목록", emptyTitle: "Workflow가 없습니다.", emptyDescription: "필터를 바꾸거나 새 파이프라인을 실행하세요.", canNext: Boolean(workflows.data?.nextCursor), canPrevious: Boolean(cursor) }}><DataTable.Frame><DataTable.Toolbar>{filter}</DataTable.Toolbar><DataTable.Content /><DataTable.Pagination /></DataTable.Frame></DataTable.Provider></Tabs.Content><Tabs.Content value="batches" className="mt-4"><DataTable.Provider rows={batches.data?.items ?? []} columns={BATCH_COLUMNS} getRowId={(row) => String(row.id)} state={{ initialLoading: batches.isLoading, refreshing: batches.isFetching && !batches.isLoading, placeholder: batches.isPlaceholderData, error: batches.error?.message ?? null }} actions={{ next: () => updateUrl({ cursor: String(batches.data?.nextCursor) }), previous: () => updateUrl({ cursor: undefined }) }} meta={{ label: "Batch 목록", emptyTitle: "Batch가 없습니다.", emptyDescription: "실행 명령이 만들어지면 여기에 표시됩니다.", canNext: Boolean(batches.data?.nextCursor), canPrevious: Boolean(cursor) }}><DataTable.Frame><DataTable.Toolbar>{filter}</DataTable.Toolbar><DataTable.Content /><DataTable.Pagination /></DataTable.Frame></DataTable.Provider></Tabs.Content><Tabs.Content value="work" className="mt-4"><DataTable.Provider rows={work.data?.items ?? []} columns={WORK_COLUMNS} getRowId={(row) => String(row.id)} state={{ initialLoading: work.isLoading, refreshing: work.isFetching && !work.isLoading, placeholder: work.isPlaceholderData, error: work.error?.message ?? null }} actions={{ next: () => updateUrl({ cursor: String(work.data?.nextCursor) }), previous: () => updateUrl({ cursor: undefined }) }} meta={{ label: "Work item 목록", emptyTitle: "Work item이 없습니다.", emptyDescription: "필터를 바꾸거나 작업을 실행하세요.", canNext: Boolean(work.data?.nextCursor), canPrevious: Boolean(cursor) }}><DataTable.Frame><DataTable.Toolbar>{filter}</DataTable.Toolbar><DataTable.Content /><DataTable.Pagination /></DataTable.Frame></DataTable.Provider></Tabs.Content></Tabs.Root></>;
}

function TabTrigger({ value, children }: { value: string; children: React.ReactNode }) { return <Tabs.Trigger value={value} className="min-h-9 rounded px-3 text-sm font-medium text-[var(--muted)] data-[state=active]:bg-[var(--accent-soft)] data-[state=active]:text-[var(--accent-strong)]">{children}</Tabs.Trigger>; }
