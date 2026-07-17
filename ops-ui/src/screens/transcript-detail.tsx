"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";

import { ActionDialog } from "@/components/action-dialog";
import { JsonInspector } from "@/components/json-inspector";
import { PageHeader } from "@/components/page-header";
import { VirtualList } from "@/components/virtual-list";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import type { TranscriptArtifacts } from "@/features/content/api";
import { useDeleteTranscript, useTranscriptArtifacts } from "@/features/content/api";

export function TranscriptDetailScreen({ id, initialData }: { id: number; initialData: TranscriptArtifacts | null }) {
  const router = useRouter(); const query = useTranscriptArtifacts(id, initialData); const deletion = useDeleteTranscript(id); const data = query.data; const metadata = data?.metadata;
  return <><PageHeader eyebrow="콘텐츠 / 자막" heading={`자막 #${id}`} description={metadata ? `${metadata.language} · ${metadata.videoId} · ${metadata.segmentCount} segments` : "자막과 cue를 불러오는 중입니다."} actions={<div className="flex gap-2"><Link href="/content/transcripts" className="self-center text-sm text-[var(--accent-strong)] hover:underline">목록으로</Link><ActionDialog.Provider heading={`자막 #${id} 삭제`} description="자막 메타데이터와 연결된 저장 정보를 삭제합니다. 대상 ID와 사유가 모두 필요합니다." confirmLabel="삭제" confirmationValue={String(id)} reasonRequired tone="danger" onConfirm={async (reason) => { await deletion.mutateAsync(reason); router.push("/content/transcripts"); }}><ActionDialog.Trigger><Button variant="destructive">삭제</Button></ActionDialog.Trigger><ActionDialog.Content><ActionDialog.ConfirmationField /><ActionDialog.ReasonField /><ActionDialog.ErrorMessage /><ActionDialog.Footer /></ActionDialog.Content></ActionDialog.Provider></div>} />
    <div className="grid gap-4 xl:grid-cols-2"><Panel.Root><Panel.Header><Panel.Title>원문</Panel.Title><Panel.Description>{data?.content?.isGenerated ? "ASR generated" : "YouTube caption"}</Panel.Description></Panel.Header><Panel.Body><p className="max-h-[38rem] overflow-auto whitespace-pre-wrap text-sm leading-6">{data?.content?.text ?? "원문이 없습니다."}</p></Panel.Body></Panel.Root><Panel.Root><Panel.Header><Panel.Title>Cues</Panel.Title><Panel.Description>{data?.cues?.cueCount ?? 0}개 · 50개 초과 시 가상화</Panel.Description></Panel.Header><VirtualList label="자막 cue 목록" items={data?.cues?.items ?? []} estimateSize={72} renderItem={(cue) => <div className="grid min-h-[72px] gap-1 px-4 py-2 sm:grid-cols-[9rem_minmax(0,1fr)]"><code className="text-xs" translate="no">{cue.cueId}<br />{cue.startMs}–{cue.endMs}ms</code><p className="text-sm">{cue.text}</p></div>} /></Panel.Root></div>
    <div className="mt-4 grid gap-4 xl:grid-cols-2"><Panel.Root><Panel.Header><Panel.Title>Prompt cues</Panel.Title><Panel.Description>LLM 입력용 cue 직렬화</Panel.Description></Panel.Header><JsonInspector value={data?.promptCues} /></Panel.Root><Panel.Root><Panel.Header><Panel.Title>메타데이터</Panel.Title></Panel.Header><JsonInspector value={metadata} /></Panel.Root></div>
  </>;
}
