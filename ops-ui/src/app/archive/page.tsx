import { ArchivePage } from "@/components/pages/archive-page";
import type { ArchiveOpsVideoFilters } from "@/lib/types";
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
  return <ArchivePage initialFilters={parseFilters(params)} />;
}

function parseFilters(params: RawSearchParams): ArchiveOpsVideoFilters {
  return {
    environment: stringParam(params.environment),
    channelId: positiveNumberParam(params.channelId),
    publishStatus: publishStatusParam(params.publishStatus),
    search: stringParam(params.search),
    limit: positiveNumberParam(params.limit) ?? 50,
    offset: nonNegativeNumberParam(params.offset) ?? 0,
  };
}

function publishStatusParam(
  value: string | string[] | undefined,
): ArchiveOpsVideoFilters["publishStatus"] {
  const raw = stringParam(value);
  const allowed = new Set(["not_ready", "ready", "pending", "running", "failed", "published"]);
  return raw && allowed.has(raw) ? (raw as ArchiveOpsVideoFilters["publishStatus"]) : undefined;
}
