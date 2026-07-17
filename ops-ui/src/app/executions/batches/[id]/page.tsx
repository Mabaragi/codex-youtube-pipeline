import { createServerApi } from "@/lib/api";
import { ExecutionDetail } from "@/screens/execution-detail";

export const dynamic = "force-dynamic";

export default async function BatchPage({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id);
  const { data } = await createServerApi().GET("/ops/work-batches/{batch_id}", { params: { path: { batch_id: id } }, cache: "no-store" });
  return <ExecutionDetail kind="batch" id={id} initialData={data ?? null} />;
}
