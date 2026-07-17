import { CommandCenter } from "@/screens/command-center";
import { createServerApi } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function CommandCenterPage() {
  const api = createServerApi();
  const [statusResult, processesResult, incidentsResult, workResult, summaryResult, publicationResult] = await Promise.allSettled([
    api.GET("/ops/automation/status", { cache: "no-store" }),
    api.GET("/ops/automation/processes", { cache: "no-store" }),
    api.GET("/ops/incidents", { params: { query: { state: "open", limit: 20 } }, cache: "no-store" }),
    api.GET("/ops/work-items", { params: { query: { status: "running", limit: 20 } }, cache: "no-store" }),
    api.GET("/ops/summary", { cache: "no-store" }),
    api.GET("/ops/archive/current", { cache: "no-store" }),
  ]);
  const status = statusResult.status === "fulfilled" ? statusResult.value.data ?? null : null;
  const processes = processesResult.status === "fulfilled" ? processesResult.value.data ?? null : null;
  const incidents = incidentsResult.status === "fulfilled" ? incidentsResult.value.data ?? null : null;
  const work = workResult.status === "fulfilled" ? workResult.value.data ?? null : null;
  const summary = summaryResult.status === "fulfilled" ? summaryResult.value.data ?? null : null;
  const publication = publicationResult.status === "fulfilled" ? publicationResult.value.data ?? null : null;
  return <CommandCenter initialStatus={status} initialProcesses={processes} initialIncidents={incidents} initialWork={work} initialSummary={summary} initialPublication={publication} />;
}
