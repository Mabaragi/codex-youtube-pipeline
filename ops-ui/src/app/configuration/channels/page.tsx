import { createServerApi } from "@/lib/api";
import { ChannelsConsole } from "@/screens/channels-console";

export const dynamic = "force-dynamic";

export default async function ChannelsPage() {
  const api = createServerApi(); const [channelsResult, streamersResult] = await Promise.allSettled([api.GET("/ops/channels", { cache: "no-store" }), api.GET("/ops/streamers", { cache: "no-store" })]);
  return <ChannelsConsole initialChannels={channelsResult.status === "fulfilled" ? channelsResult.value.data ?? null : null} initialStreamers={streamersResult.status === "fulfilled" ? streamersResult.value.data ?? null : null} />;
}
