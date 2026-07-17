"use client";

import Link from "next/link";

import { ActionDialog } from "@/components/action-dialog";
import { JsonInspector } from "@/components/json-inspector";
import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import type { Incident } from "@/features/automation/api";
import { useIncident, useIncidentAction, useUpdateIncident } from "@/features/automation/api";
import { formatDateTime } from "@/lib/format";

export function IncidentDetail({ id, initialData }: { id: number; initialData: Incident | null }) {
  const query = useIncident(id, initialData);
  const update = useUpdateIncident(id);
  const remediate = useIncidentAction(id);
  const item = query.data;
  const hasWorkItem = item?.workItemId != null;
  async function transition(state: "acknowledged" | "resolved" | "suppressed", note: string) { await update.mutateAsync({ state, note }); }
  async function action(value: "retry" | "recover_lease" | "extend_timeout") {
    await remediate.mutateAsync({ action: value, parameters: value === "extend_timeout" ? { extensionSeconds: 1800 } : {}, idempotencyKey: crypto.randomUUID() });
  }
  return <>
    <PageHeader eyebrow="복구 관제 / Incident" heading={`Incident #${id}`} description="원인 fingerprint, 연결된 실행과 허용된 복구 조치를 확인합니다." actions={<Link href="/incidents" className="text-sm text-[var(--accent-strong)] hover:underline">목록으로</Link>} />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(22rem,.75fr)]">
      <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>{item?.incidentType ?? "Incident"}</Panel.Title><Panel.Description><span translate="no">{item?.fingerprint ?? "—"}</span></Panel.Description></Panel.HeadingGroup><div className="flex gap-2">{item && <><StatusBadge value={item.severity} /><StatusBadge value={item.state} /></>}</div></Panel.Header><Panel.Body>
        {item ? <dl className="grid gap-3 sm:grid-cols-2"><Field label="errorType" value={item.errorType ?? "—"} /><Field label="taskType" value={item.taskType ?? "—"} /><Field label="workItemId" value={item.workItemId ?? "—"} /><Field label="workflowRunId" value={item.workflowRunId ?? "—"} /><Field label="occurrenceCount" value={item.occurrenceCount} /><Field label="firstSeenAt" value={formatDateTime(item.firstSeenAt)} /><Field label="lastSeenAt" value={formatDateTime(item.lastSeenAt)} /><Field label="resolvedAt" value={formatDateTime(item.resolvedAt)} /></dl> : <p role="status" className="text-sm text-[var(--muted)]">불러오는 중…</p>}
        {item?.errorMessage && <p className="mt-4 rounded-md border border-[var(--danger)]/30 bg-[var(--danger-soft)] p-3 text-sm" translate="no">{item.errorMessage}</p>}
      </Panel.Body></Panel.Root>
      <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>상태와 복구</Panel.Title><Panel.Description>서버가 허용한 조치만 실행</Panel.Description></Panel.HeadingGroup></Panel.Header><Panel.Body className="grid gap-4">
        <div className="flex flex-wrap gap-2">
          <StateAction label="확인 처리" state="acknowledged" id={id} disabled={update.isPending} onConfirm={transition} />
          <StateAction label="해결 처리" state="resolved" id={id} disabled={update.isPending} onConfirm={transition} />
          <StateAction label="억제" state="suppressed" id={id} disabled={update.isPending} onConfirm={transition} danger />
        </div>
        <div className="border-t pt-4"><p className="mb-2 text-xs font-semibold text-[var(--muted)]">안전 복구</p><div className="flex flex-wrap gap-2">
          {hasWorkItem ? <RemediationAction label="동일 입력 재시도" action="retry" id={id} disabled={remediate.isPending} onConfirm={action} /> : null}
          <RemediationAction label="만료 lease 복구" action="recover_lease" id={id} disabled={remediate.isPending} onConfirm={action} />
          {hasWorkItem ? <RemediationAction label="30분 연장" action="extend_timeout" id={id} disabled={remediate.isPending} onConfirm={action} /> : null}
        </div></div>
      </Panel.Body></Panel.Root>
    </div>
    <Panel.Root className="mt-4"><Panel.Header><Panel.Title>Incident metadata</Panel.Title></Panel.Header><JsonInspector value={item?.metadata} /></Panel.Root>
  </>;
}

function Field({ label, value }: { label: string; value: string | number }) { return <div><dt className="text-xs text-[var(--muted)]" translate="no">{label}</dt><dd className="mt-0.5 break-words font-mono text-sm" translate="no">{value}</dd></div>; }

function StateAction({ label, state, id, disabled, danger = false, onConfirm }: { label: string; state: "acknowledged" | "resolved" | "suppressed"; id: number; disabled: boolean; danger?: boolean; onConfirm: (state: "acknowledged" | "resolved" | "suppressed", note: string) => Promise<void> }) {
  return <ActionDialog.Provider heading={`Incident #${id} ${label}`} description={`상태를 ${state}(으)로 변경합니다. 판단 근거를 감사 기록으로 남기세요.`} confirmLabel={label} reasonRequired tone={danger ? "danger" : "default"} onConfirm={(note) => onConfirm(state, note)}><ActionDialog.Trigger><Button variant={danger ? "destructive" : "secondary"} disabled={disabled}>{label}</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ReasonField /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider>;
}

function RemediationAction({ label, action, id, disabled, onConfirm }: { label: string; action: "retry" | "recover_lease" | "extend_timeout"; id: number; disabled: boolean; onConfirm: (action: "retry" | "recover_lease" | "extend_timeout") => Promise<void> }) {
  return <ActionDialog.Provider heading={`Incident #${id} · ${label}`} description={`서버의 ${action} 정책과 retry 예산을 확인한 뒤 실행합니다.`} confirmLabel="실행" onConfirm={() => onConfirm(action)}><ActionDialog.Trigger><Button disabled={disabled}>{label}</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider>;
}
