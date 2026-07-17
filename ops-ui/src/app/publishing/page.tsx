import { createServerApi } from "@/lib/api";
import { PublishingConsole } from "@/screens/publishing-console";

export const dynamic = "force-dynamic";

export default async function PublishingPage({ searchParams }: { searchParams: Promise<{ mode?: "prod" | "dev"; environment?: string; offset?: string }> }) {
  const filters = await searchParams; const mode = filters.mode === "dev" ? "dev" : "prod"; const environment = filters.environment ?? mode; const offset = Number(filters.offset) || 0; const api = createServerApi();
  const [currentResult, videosResult] = await Promise.allSettled([api.GET("/ops/archive/current", { params: { query: { environment, publishMode: mode } }, cache: "no-store" }), api.GET("/ops/archive/videos", { params: { query: { environment, limit: 50, offset } }, cache: "no-store" })]);
  return <PublishingConsole initialCurrent={currentResult.status === "fulfilled" ? currentResult.value.data ?? null : null} initialVideos={videosResult.status === "fulfilled" ? videosResult.value.data ?? null : null} />;
}
