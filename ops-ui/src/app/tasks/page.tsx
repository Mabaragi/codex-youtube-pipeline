import { TasksPage } from "@/components/pages/tasks-page";
import type { OpsVideoTaskFilters } from "@/lib/types";
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
  return <TasksPage initialFilters={parseFilters(params)} />;
}

function parseFilters(params: RawSearchParams): OpsVideoTaskFilters {
  return {
    channelId: positiveNumberParam(params.channelId),
    taskName: stringParam(params.taskName),
    status: stringParam(params.status),
    limit: positiveNumberParam(params.limit) ?? 100,
    offset: nonNegativeNumberParam(params.offset) ?? 0,
  };
}
