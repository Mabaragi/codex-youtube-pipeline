import { createServerApi } from "@/lib/api";
import { SchemaConsole } from "@/screens/schema-console";

export const dynamic = "force-dynamic";
export default async function SchemaPage() { const { data } = await createServerApi().GET("/ops/schema-graph", { cache: "no-store" }); return <SchemaConsole initialData={data ?? null} />; }
