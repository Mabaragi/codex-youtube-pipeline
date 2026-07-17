import { createServerApi } from "@/lib/api";
import { EventsConsole } from "@/screens/events-console";

export const dynamic = "force-dynamic";
export default async function EventsPage({ searchParams }: { searchParams: Promise<{ severity?: string; eventType?: string; cursor?: string }> }) { const filters = await searchParams; const { data } = await createServerApi().GET("/ops/events", { params: { query: { severity: filters.severity as never, eventType: filters.eventType, cursor: Number(filters.cursor) || undefined, limit: 100 } }, cache: "no-store" }); return <EventsConsole initialData={data ?? null} />; }
