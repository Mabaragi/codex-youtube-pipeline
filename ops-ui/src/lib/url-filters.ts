export type RawSearchParams = Record<string, string | string[] | undefined>;

type QueryValue = boolean | number | string | null | undefined;

export function stringParam(value: string | string[] | undefined): string | undefined {
  const raw = Array.isArray(value) ? value[0] : value;
  const trimmed = raw?.trim();
  return trimmed ? trimmed : undefined;
}

export function positiveNumberParam(
  value: string | string[] | undefined,
): number | undefined {
  return parsedNumber(stringParam(value), (parsed) => parsed > 0);
}

export function nonNegativeNumberParam(
  value: string | string[] | undefined,
): number | undefined {
  return parsedNumber(stringParam(value), (parsed) => parsed >= 0);
}

export function stringFormValue(value: FormDataEntryValue | null): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed ? trimmed : undefined;
}

export function positiveNumberFormValue(
  value: FormDataEntryValue | null,
): number | undefined {
  return parsedNumber(stringFormValue(value), (parsed) => parsed > 0);
}

export function hrefWithQuery(
  path: string,
  filters: Record<string, QueryValue>,
): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

function parsedNumber(
  value: string | undefined,
  predicate: (value: number) => boolean,
): number | undefined {
  if (!value) {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) && predicate(parsed) ? parsed : undefined;
}
