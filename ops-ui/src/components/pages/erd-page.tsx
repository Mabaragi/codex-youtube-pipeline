"use client";

import { useMemo } from "react";
import { PageHeader } from "@/components/page-header";
import { ErdGraph } from "@/components/schema/erd-graph";
import { useSchemaGraph } from "@/lib/queries";
import { useOpsStore } from "@/store/use-ops-store";

export function ErdPage() {
  const { data, isLoading, error } = useSchemaGraph();
  const selectedTableId = useOpsStore((state) => state.selectedSchemaTableId);
  const selectedTable = useMemo(
    () => data?.tables.find((table) => table.id === selectedTableId) ?? null,
    [data?.tables, selectedTableId],
  );

  return (
    <>
      <PageHeader title="ERD" />
      {isLoading ? <div className="ops-panel p-4 text-sm text-slate-600">Loading...</div> : null}
      {error ? <div className="ops-panel p-4 text-sm text-red-700">{String(error)}</div> : null}
      {data ? (
        <div className="grid min-h-[720px] gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <ErdGraph graph={data} />
          <aside className="ops-panel p-4">
            <h2 className="mb-3 text-sm font-semibold">Table Inspector</h2>
            {selectedTable ? (
              <div>
                <div className="mb-3 text-lg font-semibold">{selectedTable.name}</div>
                <div className="grid gap-2">
                  {selectedTable.columns.map((column) => (
                    <div key={column.id} className="border-t border-slate-200 py-2 text-xs">
                      <div className="font-semibold">{column.name}</div>
                      <div className="text-slate-500">{column.type}</div>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {column.primaryKey ? <Pill label="PK" /> : null}
                        {column.foreignKeys.length ? <Pill label="FK" /> : null}
                        {column.unique ? <Pill label="UQ" /> : null}
                        {column.index ? <Pill label="IX" /> : null}
                        <Pill label={column.nullable ? "NULL" : "NOT NULL"} />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-sm text-slate-500">No table selected.</div>
            )}
          </aside>
        </div>
      ) : null}
    </>
  );
}

function Pill({ label }: { label: string }) {
  return <span className="rounded bg-slate-100 px-1.5 py-0.5 text-slate-600">{label}</span>;
}
