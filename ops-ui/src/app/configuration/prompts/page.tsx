import type { PromptKey } from "@/features/configuration/api";
import { createServerApi } from "@/lib/api";
import { PromptsConsole } from "@/screens/prompts-console";

export const dynamic = "force-dynamic";

export default async function PromptsPage({ searchParams }: { searchParams: Promise<{ key?: PromptKey }> }) {
  const { key = "micro_event_extract" } = await searchParams; const api = createServerApi(); const [promptsResult, detailResult] = await Promise.allSettled([api.GET("/ops/prompts", { cache: "no-store" }), api.GET("/ops/prompts/{promptKey}", { params: { path: { promptKey: key } }, cache: "no-store" })]);
  return <PromptsConsole initialPrompts={promptsResult.status === "fulfilled" ? promptsResult.value.data ?? null : null} initialDetail={detailResult.status === "fulfilled" ? detailResult.value.data ?? null : null} initialKey={key} />;
}
