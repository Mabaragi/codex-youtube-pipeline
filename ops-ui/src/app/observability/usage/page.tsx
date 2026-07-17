import { createServerApi } from "@/lib/api";
import { UsageConsole } from "@/screens/usage-console";

export const dynamic = "force-dynamic";
export default async function UsagePage({ searchParams }: { searchParams: Promise<{ model?: string; status?: string; cursor?: string }> }) { const filters = await searchParams; const { data } = await createServerApi().GET("/ops/codex-usage", { params: { query: { model: filters.model, status: filters.status as never, cursor: Number(filters.cursor) || undefined, limit: 100 } }, cache: "no-store" }); return <UsageConsole initialData={data ?? null} />; }
