import type { VideoArtifacts } from "@/features/content/api";
import { createServerApi } from "@/lib/api";
import { VideoDetailScreen } from "@/screens/video-detail";

export const dynamic = "force-dynamic";

export default async function VideoPage({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id); const api = createServerApi();
  const [detailResult, microResult, timelineResult] = await Promise.allSettled([
    api.GET("/ops/videos/{video_id}", { params: { path: { video_id: id } }, cache: "no-store" }),
    api.GET("/ops/videos/{video_id}/micro-events/latest", { params: { path: { video_id: id } }, cache: "no-store" }),
    api.GET("/ops/videos/{video_id}/timelines/latest", { params: { path: { video_id: id } }, cache: "no-store" }),
  ]);
  const detail = detailResult.status === "fulfilled" ? detailResult.value.data ?? null : null;
  const artifacts: VideoArtifacts = { microEvents: microResult.status === "fulfilled" ? microResult.value.data ?? null : null, timeline: timelineResult.status === "fulfilled" ? timelineResult.value.data ?? null : null };
  return <VideoDetailScreen id={id} initialData={detail} initialArtifacts={artifacts} />;
}
