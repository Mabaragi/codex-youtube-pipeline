import { DomainKnowledgePage } from "@/components/pages/domain-knowledge-page";
import type { DomainEntryFilters } from "@/lib/types";
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
  return <DomainKnowledgePage initialFilters={parseFilters(params)} />;
}

function parseFilters(params: RawSearchParams): DomainEntryFilters {
  return {
    q: stringParam(params.q),
    typeId: positiveNumberParam(params.typeId),
    streamerId: positiveNumberParam(params.streamerId),
    active: activeParam(params.active) ?? true,
    limit: positiveNumberParam(params.limit) ?? 200,
  };
}

function activeParam(value: string | string[] | undefined): boolean | undefined {
  const text = stringParam(value);
  if (text === "true") {
    return true;
  }
  if (text === "false") {
    return false;
  }
  return undefined;
}
