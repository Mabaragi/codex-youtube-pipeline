import { createServerApi } from "@/lib/api";
import { ExecutionDetail } from "@/screens/execution-detail";

export const dynamic = "force-dynamic";

export default async function WorkflowPage({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id);
  const { data } = await createServerApi().GET("/ops/workflows/{workflow_run_id}", { params: { path: { workflow_run_id: id } }, cache: "no-store" });
  return <ExecutionDetail kind="workflow" id={id} initialData={data ?? null} />;
}
