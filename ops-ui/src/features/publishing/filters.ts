import type { operations } from "@/generated/codex-api";

export type PublicationStatusFilter = NonNullable<
  operations["list_publications_ops_publish_publications_get"]["parameters"]["query"]
>["status"];

export const publicationStatusFilters = [
  "building",
  "ready",
  "partially_published",
  "published",
  "failed",
  "unavailable",
] satisfies PublicationStatusFilter[];

export function parsePublicationStatus(
  value: string | null | undefined,
): PublicationStatusFilter | undefined {
  return publicationStatusFilters.find((status) => status === value);
}
