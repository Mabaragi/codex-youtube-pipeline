import { TasksPage } from "@/components/pages/tasks-page";
import type { WorkItemFilters, WorkItemStatus } from "@/lib/types";
import { positiveNumberParam, stringParam, type RawSearchParams } from "@/lib/url-filters";

type PageProps = { searchParams?: Promise<RawSearchParams> };

export default async function Page({ searchParams }: PageProps) {
  return <TasksPage initialFilters={parseFilters((await searchParams) ?? {})} />;
}

function parseFilters(params: RawSearchParams): WorkItemFilters {
  return {
    taskType: stringParam(params.taskType),
    status: parseStatus(params.status),
    subjectType: stringParam(params.subjectType),
    subjectId: positiveNumberParam(params.subjectId),
    cursor: positiveNumberParam(params.cursor),
    limit: positiveNumberParam(params.limit) ?? 50,
  };
}

function parseStatus(value: string | string[] | undefined): WorkItemStatus | undefined {
  const status = stringParam(value);
  const allowed: WorkItemStatus[] = [
    "pending", "running", "succeeded", "failed", "timed_out", "blocked", "canceled",
  ];
  return allowed.includes(status as WorkItemStatus) ? (status as WorkItemStatus) : undefined;
}
