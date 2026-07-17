"use client";

import { Captions, Clapperboard, FileJson, GitBranch, Megaphone, Sparkles } from "lucide-react";
import { useState } from "react";

import { ActionDialog } from "@/components/action-dialog";
import { JsonInspector } from "@/components/json-inspector";
import { PageHeader } from "@/components/page-header";
import { SelectionBuilder, type SelectionValue } from "@/components/selection-builder";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { type StageOperation, useCollectVideos, useResolveChannel, useRunPipeline, useRunStage } from "@/features/operations/api";

const DEFAULT_SELECTION: SelectionValue = { type: "nextEligible", videoIds: [], channelId: null, search: "", limit: 20 };

const STAGES = [
  { key: "transcript", title: "자막 수집", description: "YouTube 자막을 수집하고 원본 메타데이터를 저장합니다.", icon: Captions },
  { key: "cue", title: "Cue 생성", description: "저장된 자막을 prompt와 탐색에 사용할 cue로 변환합니다.", icon: FileJson },
  { key: "micro", title: "마이크로 이벤트", description: "Sol medium 운영 프로필로 window 단위 이벤트를 추출합니다.", icon: Sparkles },
  { key: "timeline", title: "타임라인", description: "마이크로 이벤트를 공개 타임라인 계층으로 구성합니다.", icon: GitBranch },
  { key: "publish", title: "퍼블리시", description: "검증된 타임라인을 prod / control archive에 발행합니다.", icon: Megaphone },
] as const;

export function OperationsConsole() {
  const [selection, setSelection] = useState(DEFAULT_SELECTION);
  const [lastResult, setLastResult] = useState<unknown>(null);
  const [streamerId, setStreamerId] = useState(1);
  const [channelHandle, setChannelHandle] = useState("");
  const [channelIds, setChannelIds] = useState("");
  const pipeline = useRunPipeline();
  const resolveChannel = useResolveChannel();
  const collectVideos = useCollectVideos();
  return (
    <>
      <PageHeader eyebrow="운영 조작" heading="파이프라인 실행" description="전체 process-to-publish 또는 필요한 단계를 선택해 실행합니다. 성공한 기존 입력은 서버의 idempotency 계약에 따라 재사용됩니다." />
      <div className="grid min-w-0 gap-4 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <Panel.Root className="self-start xl:sticky xl:top-20">
          <Panel.Header><Panel.HeadingGroup><Panel.Title>대상과 기본 프로필</Panel.Title><Panel.Description>자동 운영 기본값: <span translate="no">gpt-5.6-sol / medium</span></Panel.Description></Panel.HeadingGroup></Panel.Header>
          <Panel.Body><SelectionBuilder.Provider onChange={setSelection}><SelectionBuilder.Root><SelectionBuilder.TypeField /><SelectionBuilder.CriteriaFields /></SelectionBuilder.Root></SelectionBuilder.Provider><dl className="mt-5 grid gap-2 border-t pt-4 text-xs"><ProfileRow term="Micro" value="gpt-5.6-sol · medium" /><ProfileRow term="Timeline" value="gpt-5.6-sol · medium" /><ProfileRow term="Publish" value="prod · control · v1" /><ProfileRow term="ASR fallback" value="30분마다 재확인 · 최대 6시간 · 이후 turbo/CUDA" /></dl></Panel.Body>
        </Panel.Root>
        <div className="grid min-w-0 gap-4">
          <div className="grid gap-4 md:grid-cols-2">
            <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>채널 확인</Panel.Title><Panel.Description>Streamer와 handle을 YouTube 채널로 resolve</Panel.Description></Panel.HeadingGroup></Panel.Header><Panel.Body className="grid gap-3"><label className="grid gap-1 text-xs font-medium">Streamer ID<input type="number" min={1} value={streamerId} onChange={(event) => setStreamerId(Number(event.target.value))} className="min-h-10 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" /></label><label className="grid gap-1 text-xs font-medium">Handle<input value={channelHandle} onChange={(event) => setChannelHandle(event.target.value)} className="min-h-10 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" placeholder="@channel" /></label><ActionDialog.Provider heading="채널 확인 작업 생성" description={`streamer #${streamerId}의 ${channelHandle || "handle"}을 확인합니다.`} confirmLabel="작업 생성" onConfirm={async () => { setLastResult(await resolveChannel.mutateAsync({ streamerId, handle: channelHandle })); }}><ActionDialog.Trigger><Button disabled={!channelHandle.trim()}>채널 확인</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider></Panel.Body></Panel.Root>
            <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>영상 수집</Panel.Title><Panel.Description>채널 ID 목록의 최신 영상을 수집</Panel.Description></Panel.HeadingGroup></Panel.Header><Panel.Body className="grid gap-3"><label className="grid gap-1 text-xs font-medium">Channel IDs<input value={channelIds} onChange={(event) => setChannelIds(event.target.value)} className="min-h-10 rounded-md border bg-[var(--surface)] px-3 font-mono text-sm" placeholder="1, 2, 3" /></label><ActionDialog.Provider heading="영상 수집 작업 생성" description={`채널 ${channelIds || "ID 목록"}의 최신 영상을 수집합니다.`} confirmLabel="작업 생성" onConfirm={async () => { const ids = channelIds.split(",").map(Number).filter((value) => Number.isInteger(value) && value > 0); setLastResult(await collectVideos.mutateAsync(ids)); }}><ActionDialog.Trigger><Button disabled={!channelIds.trim()}>영상 수집</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider></Panel.Body></Panel.Root>
          </div>
          <Panel.Root className="border-[var(--accent)]">
            <Panel.Header><Panel.HeadingGroup><Panel.Title>전체 Process-to-Publish</Panel.Title><Panel.Description>자막 분기부터 archive 퍼블리시까지 workflow v2로 연결합니다.</Panel.Description></Panel.HeadingGroup><Clapperboard aria-hidden="true" className="size-5 text-[var(--accent)]" /></Panel.Header>
            <Panel.Body className="flex flex-wrap items-center justify-between gap-3"><p className="max-w-2xl text-sm text-[var(--muted)]">프로덕션 publish를 포함합니다. 대상과 모델·reasoning·archive 설정을 확인한 뒤 실행하세요.</p><ActionDialog.Provider heading="전체 파이프라인 실행" description={`선택한 ${selection.type} 대상에 Sol medium workflow를 생성하고 성공 결과를 prod로 퍼블리시합니다.`} confirmLabel="Workflow 생성" onConfirm={async () => { setLastResult(await pipeline.mutateAsync(selection)); }}><ActionDialog.Trigger><Button variant="primary">전체 실행</Button></ActionDialog.Trigger><ActionDialog.Content><SelectionSummary selection={selection} /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider></Panel.Body>
          </Panel.Root>
          <section aria-labelledby="stage-heading"><h2 id="stage-heading" className="mb-3 text-sm font-semibold">단계별 실행</h2><div className="grid gap-3 md:grid-cols-2">{STAGES.map((stage) => <StageCard key={stage.key} stage={stage.key} title={stage.title} description={stage.description} icon={<stage.icon aria-hidden="true" />} selection={selection} onResult={setLastResult} />)}</div></section>
          <Panel.Root>
            <Panel.Header><Panel.HeadingGroup><Panel.Title>최근 요청 결과</Panel.Title><Panel.Description>현재 브라우저에서 마지막으로 실행한 명령 응답</Panel.Description></Panel.HeadingGroup></Panel.Header>
            <JsonInspector value={lastResult} empty="아직 실행한 명령이 없습니다." />
          </Panel.Root>
        </div>
      </div>
    </>
  );
}

function StageCard({ stage, title, description, icon, selection, onResult }: { stage: StageOperation; title: string; description: string; icon: React.ReactNode; selection: SelectionValue; onResult: (value: unknown) => void }) {
  const mutation = useRunStage(stage);
  return <Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>{title}</Panel.Title><Panel.Description>{description}</Panel.Description></Panel.HeadingGroup><span className="text-[var(--accent)]">{icon}</span></Panel.Header><Panel.Body className="flex justify-end"><ActionDialog.Provider heading={`${title} 실행`} description={`${selection.type} 대상에 ${title} 작업을 enqueue합니다.`} confirmLabel="작업 생성" onConfirm={async () => { onResult(await mutation.mutateAsync(selection)); }}><ActionDialog.Trigger><Button>{title} 실행</Button></ActionDialog.Trigger><ActionDialog.Content><SelectionSummary selection={selection} /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider></Panel.Body></Panel.Root>;
}

function SelectionSummary({ selection }: { selection: SelectionValue }) { return <div className="rounded-md border bg-[var(--surface-muted)] p-3 text-sm"><p className="font-semibold">요청 요약</p><pre className="mt-2 whitespace-pre-wrap font-mono text-xs" translate="no">{JSON.stringify(selection, null, 2)}</pre></div>; }
function ProfileRow({ term, value }: { term: string; value: string }) { return <div className="flex items-center justify-between gap-3"><dt className="text-[var(--muted)]">{term}</dt><dd className="font-mono text-right" translate="no">{value}</dd></div>; }
