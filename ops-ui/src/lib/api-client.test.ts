import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, requestJson, shouldRetryApiRequest } from "./api-client";

describe("requestJson", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("preserves auth status when Basic Auth returns a non-json response", async () => {
    const response = new Response("<html>unauthorized</html>", {
      status: 401,
      statusText: "Unauthorized",
      headers: { "content-type": "text/html" },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));

    let error: unknown;
    try {
      await requestJson("/ops/summary");
    } catch (caught) {
      error = caught;
    }

    expect(error).toBeInstanceOf(ApiClientError);
    expect(error).toMatchObject({
      status: 401,
      message: expect.stringContaining("stale Basic Auth credentials"),
    });
  });
});

describe("shouldRetryApiRequest", () => {
  it("does not retry client/auth failures", () => {
    const authError = new ApiClientError(
      "access denied",
      new Response("{}", { status: 403, statusText: "Forbidden" }),
      {},
    );
    const badRequestError = new ApiClientError(
      "bad request",
      new Response("{}", { status: 422, statusText: "Unprocessable Entity" }),
      {},
    );

    expect(shouldRetryApiRequest(0, authError)).toBe(false);
    expect(shouldRetryApiRequest(0, badRequestError)).toBe(false);
  });

  it("limits retries for transient failures", () => {
    const serverError = new ApiClientError(
      "unavailable",
      new Response("{}", { status: 503, statusText: "Service Unavailable" }),
      {},
    );

    expect(shouldRetryApiRequest(0, serverError)).toBe(true);
    expect(shouldRetryApiRequest(1, serverError)).toBe(true);
    expect(shouldRetryApiRequest(2, serverError)).toBe(false);
    expect(shouldRetryApiRequest(2, new TypeError("network failed"))).toBe(false);
  });
});
