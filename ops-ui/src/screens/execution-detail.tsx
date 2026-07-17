"use client";

import Link from "next/link";

import { ActionDialog } from "@/components/action-dialog";
import { JsonInspector } from "@/components/json-inspector";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/ui/panel";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { BatchDetail, WorkItemDetail, WorkflowDetail } from "@/features/work/api";
import { useBatch, useCancelWorkItem, useRetryWorkItem, useWorkflow, useWorkItem } from "@/features/work/api";
import { formatDateTime } from "@/lib/format";

type DetailProps =
  | { kind: "work"; id: number; initialData: WorkItemDetail | null }
  | { kind: "workflow"; id: number; initialData: WorkflowDetail | null }
  | { kind: "batch"; id: number; initialData: BatchDetail | null };

export function ExecutionDetail(props: DetailProps) {
  if (props.kind === "work") return <WorkDetail id={props.id} initialData={props.initialData} />;
  if (props.kind === "workflow") return <WorkflowDetailView id={props.id} initialData={props.initialData} />;
  return <BatchDetailView id={props.id} initialData={props.initialData} />;
}

function WorkDetail({ id, initialData }: { id: number; initialData: WorkItemDetail | null }) {
  const query = useWorkItem(id, initialData);
  const retry = useRetryWorkItem(id);
  const cancel = useCancelWorkItem(id);
  const item = query.data;
  return <>
    <PageHeader eyebrow="실행 추적 / Work item" heading={`Work item #${id}`} description="입력, lease, attempt, 오류와 결과를 한 화면에서 확인합니다." actions={<Link className="text-sm text-[var(--accent-strong)] hover:underline" href="/executions?tab=work">목록으로</Link>} />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(20rem,.6fr)]">
      <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>실행 상태</Panel.Title><Panel.Description>worker claim과 최종 outcome</Panel.Description></Panel.HeadingGroup>{item && <StatusBadge value={item.status} />}</Panel.Header><Panel.Body>
        {query.error ? <p role="alert" className="text-sm text-[var(--danger)]">{query.error.message}</p> : item ? <DefinitionGrid entries={[
          ["taskType", item.taskType], ["subject", `${item.subjectType}:${item.subjectId ?? "—"}`], ["executionMode", item.executionMode], ["leaseOwner", item.leaseOwner ?? "—"], ["leaseExpiresAt", formatDateTime(item.leaseExpiresAt)], ["timeout", `${item.timeoutSeconds}s`], ["outcomeCode", item.outcomeCode ?? "—"], ["errorCode", item.errorCode ?? "—"], ["updatedAt", formatDateTime(item.updatedAt)],
        ]} /> : <p role="status" className="text-sm text-[var(--muted)]">불러오는 중…</p>}
        {item?.errorMessage && <p className="mt-4 rounded-md border border-[var(--danger)]/30 bg-[var(--danger-soft)] p-3 text-sm" translate="no">{item.errorMessage}</p>}
      </Panel.Body></Panel.Root>
      <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>안전 조작</Panel.Title><Panel.Description>실패 재시도 또는 실행 중 취소</Panel.Description></Panel.HeadingGroup></Panel.Header><Panel.Body className="flex flex-wrap gap-2">
        <ActionDialog.Provider heading={`Work item #${id} 재시도`} description="동일 입력으로 기존 작업을 재개합니다. 성공한 작업은 다시 실행하지 않습니다." confirmLabel="재시도" onConfirm={async () => { await retry.mutateAsync(false); }}><ActionDialog.Trigger><Button disabled={!item || retry.isPending}>재시도</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider>
        <ActionDialog.Provider heading={`Work item #${id} 취소`} description="현재 실행을 취소 요청합니다. worker 체크포인트는 보존됩니다." confirmLabel="취소 요청" reasonRequired tone="danger" onConfirm={async (reason) => { await cancel.mutateAsync(reason); }}><ActionDialog.Trigger><Button variant="destructive" disabled={!item || cancel.isPending || !["pending", "running", "blocked"].includes(item.status)}>취소</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ReasonField /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider>
      </Panel.Body></Panel.Root>
    </div>
    <div className="mt-4 grid gap-4 xl:grid-cols-2"><DataPanel title="입력" value={item?.input} /><DataPanel title="출력" value={item?.output} /></div>
    <Panel.Root className="mt-4"><Panel.Header><Panel.HeadingGroup><Panel.Title>Attempts</Panel.Title><Panel.Description>최근 실행 시도와 worker 진단</Panel.Description></Panel.HeadingGroup></Panel.Header><Panel.Body><JsonInspector value={item?.attempts} /></Panel.Body></Panel.Root>
  </>;
}

function WorkflowDetailView({ id, initialData }: { id: number; initialData: WorkflowDetail | null }) {
  const query = useWorkflow(id, initialData);
  const item = query.data;
  return <>
    <PageHeader eyebrow="실행 추적 / Workflow" heading={`Workflow #${id}`} description="단계 dependency, 대기 사유, SLA와 provenance를 추적합니다." actions={<Link className="text-sm text-[var(--accent-strong)] hover:underline" href="/executions?tab=workflows">목록으로</Link>} />
    <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>{item?.workflowType ?? "Workflow"}</Panel.Title><Panel.Description>video <span translate="no">#{item?.videoId ?? "—"}</span></Panel.Description></Panel.HeadingGroup>{item && <StatusBadge value={item.status} />}</Panel.Header><Panel.Body>{item ? <DefinitionGrid entries={[
      ["currentStage", item.currentStage ?? "—"], ["waitingReason", item.waitingReason ?? "—"], ["errorCode", item.errorCode ?? "—"], ["captionSlaDeadline", formatDateTime(item.captionSlaDeadline)], ["asrSlaDeadline", formatDateTime(item.asrSlaDeadline)], ["availableAt", formatDateTime(item.availableAt)], ["updatedAt", formatDateTime(item.updatedAt)],
    ]} /> : <p role="status" className="text-sm text-[var(--muted)]">불러오는 중…</p>}</Panel.Body></Panel.Root>
    <div className="mt-4 grid gap-4 xl:grid-cols-2"><DataPanel title="단계" value={item?.steps} /><DataPanel title="Workflow 옵션·출력" value={{ options: item?.options, output: item?.output, inputHash: item?.inputHash }} /></div>
  </>;
}

function BatchDetailView({ id, initialData }: { id: number; initialData: BatchDetail | null }) {
  const query = useBatch(id, initialData);
  const item = query.data;
  return <>
    <PageHeader eyebrow="실행 추적 / Batch" heading={`Batch #${id}`} description="선택 조건과 생성된 work item 묶음을 확인합니다." actions={<Link className="text-sm text-[var(--accent-strong)] hover:underline" href="/executions?tab=batches">목록으로</Link>} />
    <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>{item?.operationType ?? "Batch"}</Panel.Title><Panel.Description>{item?.actorType ?? "—"} · 요청 {item?.requestedCount ?? 0}건</Panel.Description></Panel.HeadingGroup>{item && <StatusBadge value={item.status} />}</Panel.Header><Panel.Body>{item ? <DefinitionGrid entries={[["createdAt", formatDateTime(item.createdAt)], ["completedAt", formatDateTime(item.completedAt)], ["itemCount", String(item.items.length)]]} /> : <p role="status" className="text-sm text-[var(--muted)]">불러오는 중…</p>}</Panel.Body></Panel.Root>
    <div className="mt-4 grid gap-4 xl:grid-cols-2"><DataPanel title="선택·옵션" value={{ selection: item?.selection, options: item?.options }} /><DataPanel title="Batch items" value={item?.items} /></div>
  </>;
}

function DefinitionGrid({ entries }: { entries: [string, string][] }) {
  return <dl className="grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">{entries.map(([label, value]) => <div key={label} className="min-w-0"><dt className="text-xs text-[var(--muted)]" translate="no">{label}</dt><dd className="mt-0.5 break-words font-mono text-sm" translate="no">{value}</dd></div>)}</dl>;
}

function DataPanel({ title, value }: { title: string; value: unknown }) {
  return <Panel.Root><Panel.Header><Panel.Title>{title}</Panel.Title></Panel.Header><JsonInspector value={value} /></Panel.Root>;
}
