import { createServerApi } from "@/lib/api";
import { KnowledgeConsole } from "@/screens/knowledge-console";

export const dynamic = "force-dynamic";

export default async function KnowledgePage() {
  const api = createServerApi(); const [entriesResult, streamersResult] = await Promise.allSettled([api.GET("/ops/domain-entries", { params: { query: { active: true, limit: 200 } }, cache: "no-store" }), api.GET("/ops/streamers", { cache: "no-store" })]);
  return <KnowledgeConsole initialEntries={entriesResult.status === "fulfilled" ? entriesResult.value.data ?? null : null} initialStreamers={streamersResult.status === "fulfilled" ? streamersResult.value.data ?? null : null} />;
}
