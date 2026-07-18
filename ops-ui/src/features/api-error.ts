export function apiError(error: unknown, fallback = "API 요청을 완료하지 못했습니다."): Error {
  if (error && typeof error === "object") {
    const envelope = "error" in error ? error.error : error;
    if (envelope && typeof envelope === "object" && "message" in envelope) {
      const message = String(envelope.message);
      const code = "code" in envelope ? String(envelope.code) : null;
      const missing = missingPreconditions(envelope);
      const description = code ? `${code}: ${message}` : message;
      return new Error(missing ? `${description} Missing preconditions: ${missing}` : description);
    }
    if ("detail" in error && typeof error.detail === "string") {
      return new Error(error.detail);
    }
  }
  return new Error(fallback);
}

function missingPreconditions(envelope: object): string | null {
  if (!("details" in envelope) || !envelope.details || typeof envelope.details !== "object") return null;
  const details = envelope.details;
  if (!("missingPreconditions" in details) || !Array.isArray(details.missingPreconditions)) return null;
  return details.missingPreconditions.map((item) => JSON.stringify(item)).join("; ");
}
