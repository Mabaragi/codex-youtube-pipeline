import { createServerApi } from "@/lib/api";
import { IncidentsConsole } from "@/screens/incidents-console";

export const dynamic = "force-dynamic";

export default async function IncidentsPage({ searchParams }: { searchParams: Promise<{ state?: "open" | "acknowledged" | "resolved" | "suppressed" }> }) {
  const { state = "open" } = await searchParams;
  const { data } = await createServerApi().GET("/ops/incidents", { params: { query: { state, limit: 100 } }, cache: "no-store" });
  return <IncidentsConsole initialData={data ?? null} />;
}
