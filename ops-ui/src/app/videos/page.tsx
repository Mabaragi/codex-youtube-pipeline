import { VideosPage } from "@/components/pages/videos-page";
import type { OpsVideoFilters } from "@/lib/types";
import {
  nonNegativeNumberParam,
  positiveNumberParam,
  stringParam,
  type RawSearchParams,
} from "@/lib/url-filters";

type PageProps = {
  searchParams?: Promise<RawSearchParams>;
};

export default async function Page({ searchParams }: PageProps) {
  const params = (await searchParams) ?? {};
  return <VideosPage initialFilters={parseFilters(params)} />;
}

function parseFilters(params: RawSearchParams): OpsVideoFilters {
  return {
    channelId: positiveNumberParam(params.channelId),
    search: stringParam(params.search),
    taskStatus: stringParam(params.taskStatus),
    limit: positiveNumberParam(params.limit) ?? 100,
    offset: nonNegativeNumberParam(params.offset) ?? 0,
  };
}
