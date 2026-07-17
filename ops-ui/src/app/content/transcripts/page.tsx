import { createServerApi } from "@/lib/api";
import { TranscriptsConsole } from "@/screens/transcripts-console";

export const dynamic = "force-dynamic";

export default async function TranscriptsPage({ searchParams }: { searchParams: Promise<{ videoId?: string; languageCode?: string; offset?: string }> }) {
  const filters = await searchParams; const offset = Number(filters.offset) || 0;
  const { data } = await createServerApi().GET("/ops/transcripts", { params: { query: { videoId: filters.videoId, languageCode: filters.languageCode, limit: 50, offset } }, cache: "no-store" });
  return <TranscriptsConsole initialData={data ?? null} />;
}
