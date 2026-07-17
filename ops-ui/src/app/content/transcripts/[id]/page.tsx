import type { TranscriptArtifacts } from "@/features/content/api";
import { createServerApi } from "@/lib/api";
import { TranscriptDetailScreen } from "@/screens/transcript-detail";

export const dynamic = "force-dynamic";

export default async function TranscriptPage({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id); const api = createServerApi();
  const [metadataResult, contentResult, cuesResult, promptResult] = await Promise.allSettled([
    api.GET("/ops/transcripts/{transcript_id}", { params: { path: { transcript_id: id } }, cache: "no-store" }),
    api.GET("/ops/transcripts/{transcript_id}/content", { params: { path: { transcript_id: id } }, cache: "no-store" }),
    api.GET("/ops/transcripts/{transcript_id}/cues", { params: { path: { transcript_id: id } }, cache: "no-store" }),
    api.GET("/ops/transcripts/{transcript_id}/prompt-cues", { params: { path: { transcript_id: id } }, cache: "no-store" }),
  ]);
  const data: TranscriptArtifacts = { metadata: metadataResult.status === "fulfilled" ? metadataResult.value.data ?? null : null, content: contentResult.status === "fulfilled" ? contentResult.value.data ?? null : null, cues: cuesResult.status === "fulfilled" ? cuesResult.value.data ?? null : null, promptCues: promptResult.status === "fulfilled" ? promptResult.value.data ?? null : null };
  return <TranscriptDetailScreen id={id} initialData={data} />;
}
