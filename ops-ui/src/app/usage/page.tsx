import { UsagePage } from "@/components/pages/usage-page";
import type { CodexUsageFilters } from "@/lib/types";
import {
  positiveNumberParam,
  stringParam,
  type RawSearchParams,
} from "@/lib/url-filters";

type PageProps = {
  searchParams?: Promise<RawSearchParams>;
};

export default async function Page({ searchParams }: PageProps) {
  const params = (await searchParams) ?? {};
  return <UsagePage initialFilters={parseFilters(params)} />;
}

function parseFilters(params: RawSearchParams): CodexUsageFilters {
  return {
    source: stringParam(params.source),
    status: statusParam(params.status),
    model: stringParam(params.model),
    reasoningEffort: reasoningEffortParam(params.reasoningEffort),
    videoId: positiveNumberParam(params.videoId),
    videoTaskId: positiveNumberParam(params.videoTaskId),
    jobId: positiveNumberParam(params.jobId),
    cursor: positiveNumberParam(params.cursor),
    limit: positiveNumberParam(params.limit) ?? 50,
  };
}

function statusParam(
  value: string | string[] | undefined,
): CodexUsageFilters["status"] | undefined {
  const text = stringParam(value);
  return text === "succeeded" || text === "failed" ? text : undefined;
}

function reasoningEffortParam(
  value: string | string[] | undefined,
): CodexUsageFilters["reasoningEffort"] | undefined {
  const text = stringParam(value);
  return text === "low" || text === "medium" || text === "high" || text === "xhigh"
    ? text
    : undefined;
}
