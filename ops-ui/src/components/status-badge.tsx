export function StatusBadge({ status }: { status: string | null | undefined }) {
  const value = status ?? "none";
  const normalized = value.toLowerCase();
  let tone = "ops-status-muted";
  if (
    ["ok", "succeeded", "valid", "active", "published", "database"].includes(
      normalized,
    )
  ) {
    tone = "ops-status-ok";
  } else if (["info", "ready"].includes(normalized)) {
    tone = "ops-status-info";
  } else if (
    [
      "running",
      "pending",
      "warning",
      "no_transcript",
      "checking",
      "draft",
      "fallback",
    ].includes(normalized)
  ) {
    tone = "ops-status-warn";
  } else if (["failed", "timed_out", "invalid", "error"].includes(normalized)) {
    tone = "ops-status-bad";
  } else if (
    ["inactive", "none", "skipped", "canceled", "unlinked", "archived"].includes(
      normalized,
    )
  ) {
    tone = "ops-status-neutral";
  }
  return (
    <span className={`ops-status ${tone}`} translate="no">
      {value}
    </span>
  );
}
