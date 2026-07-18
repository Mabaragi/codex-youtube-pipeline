import { createServerApi } from "@/lib/api";
import { parsePublicationStatus } from "@/features/publishing/filters";
import { PublishingConsole } from "@/screens/publishing-console";

export const dynamic = "force-dynamic";

export default async function PublishingPage({ searchParams }: { searchParams: Promise<{ mode?: "prod" | "dev"; environment?: string; offset?: string; streamerId?: string; profileId?: string; status?: string }> }) {
  const filters = await searchParams; const mode: "prod" | "dev" = filters.mode === "dev" ? "dev" : "prod"; const environment = filters.environment ?? mode; const offset = Number(filters.offset) || 0; const streamerId = parseFilterId(filters.streamerId); const profileId = parseFilterId(filters.profileId); const status = parsePublicationStatus(filters.status); const api = createServerApi();
  const videosQuery = { environment, limit: 50, offset, ...(streamerId ? { streamerId } : {}), ...(profileId ? { profileId } : {}) };
  const publicationsQuery = { environment, publishMode: mode, limit: 50, offset, ...(streamerId ? { streamerId } : {}), ...(profileId ? { profileId } : {}), ...(status ? { status } : {}) };
  const [currentResult, videosResult, publicationsResult] = await Promise.allSettled([api.GET("/ops/archive/current", { params: { query: { environment, publishMode: mode } }, cache: "no-store" }), api.GET("/ops/archive/videos", { params: { query: videosQuery }, cache: "no-store" }), api.GET("/ops/publish/publications", { params: { query: publicationsQuery }, cache: "no-store" })]);
  return <PublishingConsole initialCurrent={currentResult.status === "fulfilled" ? currentResult.value.data ?? null : null} initialVideos={videosResult.status === "fulfilled" ? videosResult.value.data ?? null : null} initialPublications={publicationsResult.status === "fulfilled" ? publicationsResult.value.data ?? null : null} />;
}

function parseFilterId(value: string | undefined) { const parsed = Number(value); return Number.isInteger(parsed) && parsed > 0 ? parsed : null; }
