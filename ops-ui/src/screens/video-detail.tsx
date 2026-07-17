"use client";

import dynamic from "next/dynamic";
import Link from "next/link";

import { PageHeader } from "@/components/page-header";
import { StatusBadge } from "@/components/ui/badge";
import { Panel } from "@/components/ui/panel";
import type { VideoArtifacts, VideoDetail } from "@/features/content/api";
import { useVideo, useVideoArtifacts } from "@/features/content/api";
import { formatDateTime } from "@/lib/format";

const ArtifactViewer = dynamic(() => import("@/components/artifact-viewer"), { loading: () => <p className="p-4 text-sm text-[var(--muted)]">아티팩트 뷰어 로딩 중…</p> });

export function VideoDetailScreen({ id, initialData, initialArtifacts }: { id: number; initialData: VideoDetail | null; initialArtifacts: VideoArtifacts | null }) {
  const detail = useVideo(id, initialData); const artifacts = useVideoArtifacts(id, initialArtifacts); const item = detail.data;
  return <><PageHeader eyebrow="콘텐츠 / 영상" heading={item?.title ?? `영상 #${id}`} description={item ? `${item.channelName} · ${item.youtubeVideoId}` : "영상 상세를 불러오는 중입니다."} actions={<Link href="/content/videos" className="text-sm text-[var(--accent-strong)] hover:underline">목록으로</Link>} />
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(20rem,.8fr)]"><Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>생성 상태</Panel.Title><Panel.Description>자막부터 타임라인까지의 연결</Panel.Description></Panel.HeadingGroup>{item?.latestTaskStatus && <StatusBadge value={item.latestTaskStatus} />}</Panel.Header><Panel.Body>{item ? <dl className="grid gap-3 sm:grid-cols-2"><Field label="videoId" value={item.videoId} /><Field label="youtubeVideoId" value={item.youtubeVideoId} /><Field label="publishedAt" value={formatDateTime(item.publishedAt)} /><Field label="duration" value={`${item.duration ?? 0}s`} /><Field label="embeddable" value={String(item.isEmbeddable ?? "unknown")} /><Field label="latestTask" value={`${item.latestTaskName ?? "—"}:${item.latestTaskId ?? "—"}`} /></dl> : <p role="status">불러오는 중…</p>}</Panel.Body></Panel.Root><Panel.Root><Panel.Header><Panel.Title>자막</Panel.Title></Panel.Header><Panel.Body className="grid gap-2">{item?.transcripts.length ? item.transcripts.map((transcript) => <Link key={transcript.id} href={`/content/transcripts/${transcript.id}`} className="rounded-md border p-3 hover:bg-[var(--surface-muted)]"><span className="font-mono text-sm">#{transcript.id}</span><span className="ml-2 text-sm">{transcript.language}</span><span className="ml-2 text-xs text-[var(--muted)]">{transcript.segmentCount} segments</span></Link>) : <p className="text-sm text-[var(--muted)]">저장된 자막이 없습니다.</p>}</Panel.Body></Panel.Root></div>
    <Panel.Root className="mt-4"><Panel.Header><Panel.Title>작업 이력</Panel.Title><Panel.Description>수집·자막·생성 작업 provenance</Panel.Description></Panel.Header><Panel.Body className="grid gap-2">{item?.tasks.map((task) => <div key={task.videoTaskId} className="grid gap-2 rounded-md border p-3 md:grid-cols-[8rem_minmax(0,1fr)_8rem_12rem]"><Link href={`/executions/work-items/${task.videoTaskId}`} className="font-mono text-[var(--accent-strong)] hover:underline">#{task.videoTaskId}</Link><code translate="no">{task.taskName}</code><StatusBadge value={task.status} /><span className="ops-number text-xs">{formatDateTime(task.updatedAt)}</span></div>)}</Panel.Body></Panel.Root>
    <div className="mt-4 grid gap-4 xl:grid-cols-2"><Panel.Root><Panel.Header><Panel.Title>마이크로 이벤트</Panel.Title><Panel.Description>{artifacts.data?.microEvents ? `${artifacts.data.microEvents.microEventCount} events · ${artifacts.data.microEvents.windowCount} windows` : "아직 생성되지 않음"}</Panel.Description></Panel.Header><ArtifactViewer value={artifacts.data?.microEvents} /></Panel.Root><Panel.Root><Panel.Header><Panel.Title>타임라인</Panel.Title><Panel.Description>{artifacts.data?.timeline?.timelineState ?? "아직 생성되지 않음"}</Panel.Description></Panel.Header><ArtifactViewer value={artifacts.data?.timeline} /></Panel.Root></div>
  </>;
}

function Field({ label, value }: { label: string; value: string | number }) { return <div><dt className="text-xs text-[var(--muted)]" translate="no">{label}</dt><dd className="font-mono text-sm" translate="no">{value}</dd></div>; }
