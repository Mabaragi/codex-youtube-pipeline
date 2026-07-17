import { createServerApi } from "@/lib/api";
import { IncidentDetail } from "@/screens/incident-detail";

export const dynamic = "force-dynamic";

export default async function IncidentPage({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id);
  const { data } = await createServerApi().GET("/ops/incidents/{incident_id}", { params: { path: { incident_id: id } }, cache: "no-store" });
  return <IncidentDetail id={id} initialData={data ?? null} />;
}
