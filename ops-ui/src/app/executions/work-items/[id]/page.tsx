import { createServerApi } from "@/lib/api";
import { ExecutionDetail } from "@/screens/execution-detail";

export const dynamic = "force-dynamic";

export default async function WorkItemPage({ params }: { params: Promise<{ id: string }> }) {
  const id = Number((await params).id);
  const { data } = await createServerApi().GET("/ops/work-items/{work_item_id}", { params: { path: { work_item_id: id } }, cache: "no-store" });
  return <ExecutionDetail kind="work" id={id} initialData={data ?? null} />;
}
