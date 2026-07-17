"use client";

import { ArrowRight, CircleAlert, Cpu, Database, Play, RadioTower, Workflow } from "lucide-react";
import Link from "next/link";

import { ActionDialog } from "@/components/action-dialog";
import { ErrorNotice, RefreshStatus } from "@/components/async-state";
import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/ui/badge";
import type { AutomationStatus, IncidentList, OpsSummary, ProcessInventory } from "@/features/automation/api";
import { useAutomationStatus, useIncidents, useOpsSummary, useProcessInventory, useRuntimeTransition } from "@/features/automation/api";
import type { WorkItemList } from "@/features/work/api";
import { useWorkItems } from "@/features/work/api";
import type { ArchiveCurrent } from "@/features/publishing/api";
import { useArchiveCurrent } from "@/features/publishing/api";
import { formatDateTime, formatNumber } from "@/lib/format";

interface CommandCenterProps {
  initialStatus: AutomationStatus | null;
  initialProcesses: ProcessInventory | null;
  initialIncidents: IncidentList | null;
  initialWork: WorkItemList | null;
  initialSummary: OpsSummary | null;
  initialPublication: ArchiveCurrent | null;
}

export function CommandCenter(props: CommandCenterProps) {
  const status = useAutomationStatus(props.initialStatus);
  const processes = useProcessInventory(props.initialProcesses);
  const incidents = useIncidents({ state: "open", limit: 20 }, props.initialIncidents);
  const work = useWorkItems({ status: "running", limit: 20 }, props.initialWork);
  const summary = useOpsSummary(props.initialSummary);
  const publication = useArchiveCurrent({ environment: "prod", publishMode: "prod" }, props.initialPublication);
  const runtime = status.data?.runtime;
  const queues = summarizeQueues(status.data?.queues ?? []);

  return (
    <>
      <PageHeader
        eyebrow="운영 현황"
        heading="Command Center"
        description="로컬 파이프라인의 실행 상태, incident, 작업량과 퍼블리시 최신성을 한 화면에서 확인합니다."
        actions={<RuntimeActions state={runtime?.state ?? "stopped"} readyToStop={runtime?.readyToStop ?? false} />}
      />
      {[status.error, processes.error, incidents.error, work.error].some(Boolean) ? (
        <ErrorNotice message="일부 API가 응답하지 않았습니다. 사용 가능한 패널은 계속 표시합니다." />
      ) : null}
      <section aria-label="핵심 지표" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric label="Runtime" value={runtime?.state ?? "unavailable"} icon={<Play aria-hidden="true" />} status={runtime?.state} />
        <Metric label="열린 incident" value={formatNumber(status.data?.openIncidentCount)} icon={<CircleAlert aria-hidden="true" />} status={(status.data?.openIncidentCount ?? 0) > 0 ? "open" : "resolved"} />
        <Metric label="실행 중 work" value={formatNumber(runtime?.runningWorkItemCount)} icon={<Cpu aria-hidden="true" />} status={(runtime?.runningWorkItemCount ?? 0) > 0 ? "running" : "stopped"} />
        <Metric label="퍼블리시 영상" value={formatNumber(publication.data?.latestPublication?.videoCount)} icon={<RadioTower aria-hidden="true" />} status={publication.data?.latestPublication ? "published" : "pending"} />
      </section>
      <div className="grid min-w-0 gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <Panel.Root>
          <Panel.Header><Panel.HeadingGroup><Panel.Title>프로세스</Panel.Title><Panel.Description>{processes.data?.hostName ?? "호스트 확인 불가"}</Panel.Description></Panel.HeadingGroup><RefreshStatus refreshing={processes.isFetching} /></Panel.Header>
          <Panel.Body className="p-0"><div className="divide-y">{processes.data?.items.map((item) => <div key={item.name} className="grid grid-cols-[minmax(0,1fr)_auto] gap-3 px-4 py-2.5"><div className="min-w-0"><p className="truncate text-sm font-medium" translate="no">{item.name}</p><p className="text-xs text-[var(--muted)]"><span translate="no">{item.role}</span>{item.pid ? ` · PID ${item.pid}` : ""}</p></div><div className="text-right"><StatusBadge value={item.state} />{item.detailCode ? <p className="mt-1 text-[10px] text-[var(--muted)]" translate="no">{item.detailCode}</p> : null}</div></div>) ?? <div className="p-4 text-sm text-[var(--muted)]">프로세스 정보를 불러오지 못했습니다.</div>}</div></Panel.Body>
        </Panel.Root>
        <Panel.Root>
          <Panel.Header><Panel.HeadingGroup><Panel.Title>Queue</Panel.Title><Panel.Description>단계별 대기·실행 상태</Panel.Description></Panel.HeadingGroup></Panel.Header>
          <Panel.Body className="p-0"><div className="divide-y">{queues.length ? queues.map((queue) => <div key={queue.taskType} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm"><code className="truncate" translate="no">{queue.taskType}</code><span className="ops-number text-xs text-[var(--muted)]">pending {queue.pending} · running {queue.running} · failed {queue.failed}</span></div>) : <div className="p-4 text-sm text-[var(--muted)]">Queue가 비어 있습니다.</div>}</div></Panel.Body>
        </Panel.Root>
      </div>
      <div className="grid min-w-0 gap-4 xl:grid-cols-2">
        <Panel.Root>
          <Panel.Header><Panel.HeadingGroup><Panel.Title>열린 incident</Panel.Title><Panel.Description>자동 복구를 기다리거나 운영자 판단이 필요한 사건</Panel.Description></Panel.HeadingGroup><Button asChild variant="ghost" size="sm"><Link href="/incidents">전체 보기 <ArrowRight aria-hidden="true" /></Link></Button></Panel.Header>
          <Panel.Body className="p-0"><div className="divide-y">{incidents.data?.items.slice(0, 8).map((incident) => <Link key={incident.id} href={`/incidents/${incident.id}`} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-3 px-4 py-3 hover:bg-[var(--surface-muted)]"><span className="ops-number text-xs text-[var(--muted)]">#{incident.id}</span><div className="min-w-0"><p className="truncate text-sm font-medium" translate="no">{incident.errorType ?? incident.incidentType}</p><p className="mt-0.5 line-clamp-1 text-xs text-[var(--muted)]">{incident.errorMessage ?? "상세 오류 메시지 없음"}</p></div><StatusBadge value={incident.severity} /></Link>) ?? <div className="p-4 text-sm text-[var(--muted)]">열린 incident가 없습니다.</div>}</div></Panel.Body>
        </Panel.Root>
        <Panel.Root>
          <Panel.Header><Panel.HeadingGroup><Panel.Title>실행 중 work</Panel.Title><Panel.Description>최근 갱신 순서</Panel.Description></Panel.HeadingGroup><Button asChild variant="ghost" size="sm"><Link href="/executions?tab=work">전체 보기 <ArrowRight aria-hidden="true" /></Link></Button></Panel.Header>
          <Panel.Body className="p-0"><div className="divide-y">{work.data?.items.slice(0, 8).map((item) => <Link key={item.id} href={`/executions/work-items/${item.id}`} className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 px-4 py-3 hover:bg-[var(--surface-muted)]"><Workflow aria-hidden="true" className="size-4 text-[var(--accent)]" /><div className="min-w-0"><p className="truncate text-sm font-medium" translate="no">{item.taskType} #{item.id}</p><p className="text-xs text-[var(--muted)]">{formatDateTime(item.updatedAt)}</p></div><StatusBadge value={item.status} /></Link>) ?? <div className="p-4 text-sm text-[var(--muted)]">실행 중인 work가 없습니다.</div>}</div></Panel.Body>
        </Panel.Root>
      </div>
      <Panel.Root>
        <Panel.Header><Panel.HeadingGroup><Panel.Title>콘텐츠 인벤토리</Panel.Title><Panel.Description>API가 보고한 전체 수량과 최근 퍼블리시</Panel.Description></Panel.HeadingGroup></Panel.Header>
        <Panel.Body className="grid gap-4 sm:grid-cols-4"><Inventory label="영상" value={summary.data?.counts.videos} /><Inventory label="자막" value={summary.data?.counts.transcripts} /><Inventory label="채널" value={summary.data?.counts.channels} /><Inventory label="스트리머" value={summary.data?.counts.streamers} /><div className="sm:col-span-4 flex items-center gap-2 border-t pt-3 text-xs text-[var(--muted)]"><Database aria-hidden="true" className="size-4" />최근 publication: {formatDateTime(publication.data?.latestPublication?.createdAt)}</div></Panel.Body>
      </Panel.Root>
    </>
  );
}

function Metric({ label, value, icon, status }: { label: string; value: string; icon: React.ReactNode; status?: string }) { return <div className="ops-panel flex items-center justify-between gap-3 p-4"><div><p className="text-xs text-[var(--muted)]">{label}</p><p className="ops-number mt-1 text-xl font-semibold" translate="no">{value}</p>{status ? <div className="mt-2"><StatusBadge value={status} /></div> : null}</div><span className="grid size-9 place-items-center rounded-md bg-[var(--surface-muted)] text-[var(--accent)]">{icon}</span></div>; }
function Inventory({ label, value }: { label: string; value?: number }) { return <div><p className="text-xs text-[var(--muted)]">{label}</p><p className="ops-number mt-1 text-2xl font-semibold">{formatNumber(value)}</p></div>; }

export function summarizeQueues(queues: AutomationStatus["queues"]) {
  const grouped = new Map<string, { taskType: string; pending: number; running: number; failed: number }>();
  for (const queue of queues) {
    const taskType = typeof queue.taskType === "string" ? queue.taskType : "unknown";
    const status = typeof queue.status === "string" ? queue.status : "";
    const count = typeof queue.count === "number" ? queue.count : 0;
    const current = grouped.get(taskType) ?? {
      taskType,
      pending: 0,
      running: 0,
      failed: 0,
    };
    if (status === "pending") current.pending += count;
    if (status === "running") current.running += count;
    if (status === "failed") current.failed += count;
    grouped.set(taskType, current);
  }
  return [...grouped.values()];
}

function RuntimeActions({ state, readyToStop }: { state: string; readyToStop: boolean }) {
  return <div className="flex flex-wrap gap-2">{state === "active" ? <RuntimeDialog action="drain" label="Drain" description="새 작업 수락을 막고 실행 중 작업이 끝날 때까지 기다립니다." /> : <RuntimeDialog action="resume" label="Resume" description="scheduler와 worker가 새 작업을 다시 받을 수 있게 합니다." />}{state === "draining" && readyToStop ? <RuntimeDialog action="mark-stopped" label="Stopped 기록" description="실행 작업이 모두 종료된 runtime을 stopped 상태로 기록합니다." /> : null}</div>;
}

function RuntimeDialog({ action, label, description }: { action: "drain" | "resume" | "mark-stopped"; label: string; description: string }) {
  const mutation = useRuntimeTransition(action);
  return <ActionDialog.Provider heading={`${label} runtime`} description={description} confirmLabel={label} reasonRequired onConfirm={async (reason) => { await mutation.mutateAsync(reason); }}><ActionDialog.Trigger><Button variant={action === "drain" ? "outline" : "primary"}>{label}</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ReasonField /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider>;
}
