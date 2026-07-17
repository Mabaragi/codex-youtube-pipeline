import type { ReactNode } from "react";

export function JsonInspector({ value, empty = "데이터가 없습니다." }: { value: unknown; empty?: ReactNode }) {
  if (value == null) {
    return <div className="p-4 text-sm text-[var(--muted)]">{empty}</div>;
  }
  return (
    <pre
      data-slot="json-inspector"
      className="ops-scrollbar max-h-[34rem] overflow-auto whitespace-pre-wrap break-words p-4 font-mono text-xs leading-5"
      translate="no"
    >
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}
