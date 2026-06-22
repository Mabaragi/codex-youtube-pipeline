const BFF_BASE_URL = "/ops/api/backend";

export class ApiClientError extends Error {
  readonly status: number;
  readonly statusText: string;
  readonly payload: unknown;

  constructor(message: string, response: Response, payload: unknown) {
    super(message);
    this.name = "ApiClientError";
    this.status = response.status;
    this.statusText = response.statusText;
    this.payload = payload;
  }
}

export async function requestJson<TData>(
  path: string,
  options: {
    method?: "GET" | "POST" | "PATCH" | "DELETE";
    query?: Record<string, string | number | boolean | null | undefined>;
    body?: unknown;
  } = {},
): Promise<TData> {
  const url = new URL(`${BFF_BASE_URL}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== null && value !== undefined && value !== "") {
      url.searchParams.set(key, String(value));
    }
  }

  const response = await fetch(url, {
    method: options.method ?? "GET",
    headers: options.body === undefined ? undefined : { "content-type": "application/json" },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    cache: "no-store",
  });
  const payload = await parseJson(response);
  if (!response.ok) {
    throw new ApiClientError(formatApiError(payload, response), response, payload);
  }
  return payload as TData;
}

export function shouldRetryApiRequest(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiClientError) {
    if (error.status >= 400 && error.status < 500) {
      return false;
    }
    return failureCount < 2;
  }
  return failureCount < 2;
}

async function parseJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

function formatApiError(error: unknown, response: Response): string {
  if (response.status === 401 || response.status === 403) {
    return (
      `Access denied with HTTP ${response.status}. ` +
      "This browser profile may have stale Basic Auth credentials for this site. " +
      "Clear this site's saved password/site data, close that browser profile window, and sign in again."
    );
  }
  if (isErrorObject(error)) {
    const detail = error.detail;
    if (typeof detail === "string") {
      return detail;
    }
    return JSON.stringify(detail);
  }
  if (typeof error === "string" && error.trim() && error.length < 240) {
    return error;
  }
  return `Request failed with HTTP ${response.status}`;
}

function isErrorObject(value: unknown): value is { detail?: unknown } {
  return typeof value === "object" && value !== null && "detail" in value;
}
