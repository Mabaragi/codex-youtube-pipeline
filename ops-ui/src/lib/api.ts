import createClient from "openapi-fetch";

import type { paths } from "@/generated/codex-api";

export const BFF_BASE_URL = `${typeof window === "undefined" ? "" : window.location.origin}/ops/api/backend`;

export const browserApi = createClient<paths>({ baseUrl: BFF_BASE_URL });

export function createServerApi() {
  return createClient<paths>({
    baseUrl:
      process.env.CODEX_OPS_BACKEND_BASE_URL ?? "http://127.0.0.1:8000",
  });
}

export async function settledData<T>(promise: Promise<{ data?: T }>): Promise<T | null> {
  const [result] = await Promise.allSettled([promise]);
  return result.status === "fulfilled" ? (result.value.data ?? null) : null;
}

export function operatorReasonHeader(reason: string): string {
  return encodeURIComponent(reason);
}
