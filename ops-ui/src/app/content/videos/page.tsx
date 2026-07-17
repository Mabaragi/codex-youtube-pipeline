import { createServerApi } from "@/lib/api";
import { VideosConsole } from "@/screens/videos-console";

export const dynamic = "force-dynamic";

export default async function VideosPage({ searchParams }: { searchParams: Promise<{ search?: string; channelId?: string; offset?: string }> }) {
  const filters = await searchParams; const offset = Number(filters.offset) || 0; const channelId = Number(filters.channelId) || undefined;
  const { data } = await createServerApi().GET("/ops/videos", { params: { query: { search: filters.search, channelId, limit: 50, offset } }, cache: "no-store" });
  return <VideosConsole initialData={data ?? null} />;
}
