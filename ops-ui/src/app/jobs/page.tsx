import { JobsPage } from "@/components/pages/jobs-page";
import type { PipelineJobFilters } from "@/lib/types";
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
  return <JobsPage initialFilters={parseFilters(params)} />;
}

function parseFilters(params: RawSearchParams): PipelineJobFilters {
  return {
    channelId: positiveNumberParam(params.channelId),
    status: pipelineStatusParam(params.status),
    step: stringParam(params.step),
    cursor: positiveNumberParam(params.cursor),
    limit: positiveNumberParam(params.limit) ?? 50,
  };
}

function pipelineStatusParam(
  value: string | string[] | undefined,
): PipelineJobFilters["status"] | undefined {
  const text = stringParam(value);
  if (
    text === "pending" ||
    text === "running" ||
    text === "succeeded" ||
    text === "failed" ||
    text === "skipped" ||
    text === "canceled"
  ) {
    return text;
  }
  return undefined;
}
