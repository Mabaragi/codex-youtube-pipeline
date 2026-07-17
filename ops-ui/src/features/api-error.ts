export function apiError(error: unknown, fallback = "API 요청을 완료하지 못했습니다."): Error {
  if (error && typeof error === "object") {
    const envelope = "error" in error ? error.error : error;
    if (envelope && typeof envelope === "object" && "message" in envelope) {
      const message = String(envelope.message);
      const code = "code" in envelope ? String(envelope.code) : null;
      return new Error(code ? `${code}: ${message}` : message);
    }
    if ("detail" in error && typeof error.detail === "string") {
      return new Error(error.detail);
    }
  }
  return new Error(fallback);
}
