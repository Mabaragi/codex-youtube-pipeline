import { createServerApi } from "@/lib/api";
import { ExecutionsConsole } from "@/screens/executions-console";

export const dynamic = "force-dynamic";

export default async function ExecutionsPage({ searchParams }: { searchParams: Promise<{ status?: string; cursor?: string }> }) {
  const filters = await searchParams;
  const cursor = Number(filters.cursor) || undefined;
  const api = createServerApi();
  const results = await Promise.allSettled([
    api.GET("/ops/workflows", { params: { query: { status: filters.status as never, cursor, limit: 50 } }, cache: "no-store" }),
    api.GET("/ops/work-batches", { params: { query: { status: filters.status as never, cursor, limit: 50 } }, cache: "no-store" }),
    api.GET("/ops/work-items", { params: { query: { status: filters.status as never, cursor, limit: 50 } }, cache: "no-store" }),
  ]);
  const workflow = results[0].status === "fulfilled" ? results[0].value.data ?? null : null;
  const batches = results[1].status === "fulfilled" ? results[1].value.data ?? null : null;
  const work = results[2].status === "fulfilled" ? results[2].value.data ?? null : null;
  return <ExecutionsConsole initialWorkflows={workflow} initialBatches={batches} initialWork={work} />;
}
