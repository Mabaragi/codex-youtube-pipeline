export function StatusBadge({ status }: { status: string | null | undefined }) {
  const value = status ?? "none";
  let tone = "ops-status-muted";
  if (["ok", "succeeded", "valid"].includes(value)) {
    tone = "ops-status-ok";
  } else if (["running", "pending"].includes(value)) {
    tone = "ops-status-warn";
  } else if (["failed", "timed_out", "invalid"].includes(value)) {
    tone = "ops-status-bad";
  }
  return <span className={`ops-status ${tone}`}>{value}</span>;
}
