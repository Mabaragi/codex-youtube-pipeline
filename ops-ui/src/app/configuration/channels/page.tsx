import { createServerApi } from "@/lib/api";
import type {
  PublicationConnectionList,
  PublishProfile,
} from "@/features/publishing/api";
import { ChannelsConsole } from "@/screens/channels-console";

export const dynamic = "force-dynamic";

export default async function ChannelsPage() {
  const api = createServerApi();
  const [channelsResult, streamersResult, profilesResult, connectionsResult] =
    await Promise.allSettled([
      api.GET("/ops/channels", { cache: "no-store" }),
      api.GET("/ops/streamers", { cache: "no-store" }),
      api.GET("/ops/publish/profiles", { cache: "no-store" }),
      api.GET("/ops/publish/connections", { cache: "no-store" }),
    ]);

  return (
    <ChannelsConsole
      initialChannels={
        channelsResult.status === "fulfilled"
          ? channelsResult.value.data ?? null
          : null
      }
      initialStreamers={
        streamersResult.status === "fulfilled"
          ? streamersResult.value.data ?? null
          : null
      }
      initialProfiles={
        profilesResult.status === "fulfilled"
          ? (profilesResult.value.data as PublishProfile[] | undefined) ?? null
          : null
      }
      initialConnections={
        connectionsResult.status === "fulfilled"
          ? (connectionsResult.value.data as PublicationConnectionList | undefined) ??
            null
          : null
      }
    />
  );
}
