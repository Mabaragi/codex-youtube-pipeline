import { LogsPage } from "@/components/pages/logs-page";
import type { OperationEventFilters } from "@/lib/types";

type PageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
};

export default async function Page({ searchParams }: PageProps) {
  const params = (await searchParams) ?? {};
  return <LogsPage initialFilters={parseFilters(params)} />;
}

function parseFilters(
  params: Record<string, string | string[] | undefined>,
): OperationEventFilters {
  return {
    severity: severityParam(params.severity),
    eventType: stringParam(params.eventType),
    subjectType: stringParam(params.subjectType),
    subjectId: numberParam(params.subjectId),
    jobId: numberParam(params.jobId),
    videoTaskId: numberParam(params.videoTaskId),
    channelId: numberParam(params.channelId),
    videoId: numberParam(params.videoId),
    cursor: numberParam(params.cursor),
    limit: numberParam(params.limit) ?? 50,
  };
}

function stringParam(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  const trimmed = raw?.trim();
  return trimmed ? trimmed : undefined;
}

function numberParam(value: string | string[] | undefined): number | undefined {
  const text = stringParam(value);
  if (!text) {
    return undefined;
  }
  const parsed = Number(text);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function severityParam(
  value: string | string[] | undefined,
): OperationEventFilters["severity"] | undefined {
  const text = stringParam(value);
  return text === "info" || text === "warning" || text === "error" ? text : undefined;
}

