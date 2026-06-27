"use client";

import { useCallback, useMemo, useState } from "react";
import { PageHeader } from "@/components/page-header";
import { ErdGraph } from "@/components/schema/erd-graph";
import { getRelationCardinality } from "@/components/schema/schema-display";
import { ErrorState, LoadingState } from "@/components/ui-primitives";
import { useSchemaGraph } from "@/lib/queries";
import type { OpsSchemaGraph, OpsSchemaTable } from "@/lib/types";
import { useOpsStore } from "@/store/use-ops-store";

type SchemaColumn = OpsSchemaTable["columns"][number];
type SchemaRelation = OpsSchemaGraph["relations"][number];
type SchemaIndex = OpsSchemaTable["indexes"][number];
type SchemaUniqueConstraint = OpsSchemaTable["uniqueConstraints"][number];
type SchemaForeignKeyConstraint = OpsSchemaTable["foreignKeyConstraints"][number];

export function ErdPage() {
  const { data, isLoading, error } = useSchemaGraph();
  const selectedTableId = useOpsStore((state) => state.selectedSchemaTableId);
  const [selectedRelationId, setSelectedRelationId] = useState<string | null>(null);
  const selectedTable = useMemo(
    () => data?.tables.find((table) => table.id === selectedTableId) ?? null,
    [data?.tables, selectedTableId],
  );
  const selectedRelation = useMemo(
    () => data?.relations.find((relation) => relation.id === selectedRelationId) ?? null,
    [data?.relations, selectedRelationId],
  );
  const tableRelations = useMemo(() => {
    if (!data || !selectedTableId) {
      return { incoming: [], outgoing: [] };
    }
    return {
      incoming: data.relations.filter((relation) => relation.targetTable === selectedTableId),
      outgoing: data.relations.filter((relation) => relation.sourceTable === selectedTableId),
    };
  }, [data, selectedTableId]);
  const handleSelectRelation = useCallback((relationId: string | null) => {
    setSelectedRelationId(relationId);
  }, []);

  return (
    <>
      <PageHeader
        title="ERD"
        description="Explore schema tables, column constraints, and relationship metadata."
      />
      {isLoading ? <LoadingState /> : null}
      {error ? <ErrorState message={String(error)} /> : null}
      {data ? (
        <div className="grid min-h-[720px] gap-4 2xl:grid-cols-[minmax(0,1fr)_360px]">
          <ErdGraph
            graph={data}
            selectedRelationId={selectedRelationId}
            onSelectRelation={handleSelectRelation}
          />
          <SchemaInspector
            selectedTable={selectedTable}
            selectedRelation={selectedRelation}
            incomingRelations={tableRelations.incoming}
            outgoingRelations={tableRelations.outgoing}
          />
        </div>
      ) : null}
    </>
  );
}

function SchemaInspector({
  selectedTable,
  selectedRelation,
  incomingRelations,
  outgoingRelations,
}: {
  selectedTable: OpsSchemaTable | null;
  selectedRelation: SchemaRelation | null;
  incomingRelations: SchemaRelation[];
  outgoingRelations: SchemaRelation[];
}) {
  return (
    <aside className="ops-panel overflow-hidden 2xl:sticky 2xl:top-4 2xl:self-start">
      <div className="border-b border-slate-200 p-4">
        <h2 className="text-sm font-semibold">Schema Inspector</h2>
        <div className="mt-1 text-xs text-slate-500">
          Select a table or relationship to inspect metadata.
        </div>
      </div>
      <div className="grid max-h-[670px] gap-4 overflow-auto p-4">
        {selectedRelation ? <RelationDetail relation={selectedRelation} /> : null}
        {selectedTable ? (
          <>
            <section>
              <div className="mb-2 text-lg font-semibold">{selectedTable.name}</div>
              <div className="text-xs text-slate-500">
                {selectedTable.columns.length} columns ·{" "}
                {selectedTable.indexes.length + selectedTable.uniqueConstraints.length} indexes
                and unique constraints
              </div>
            </section>
            <InspectorSection title="Columns">
              <div className="grid gap-2">
                {selectedTable.columns.map((column) => (
                  <ColumnDetail key={column.id} column={column} />
                ))}
              </div>
            </InspectorSection>
            <InspectorSection title="Referenced Child Tables">
              <RelationList relations={outgoingRelations} emptyLabel="No child tables reference this table." />
            </InspectorSection>
            <InspectorSection title="Parent References">
              <RelationList relations={incomingRelations} emptyLabel="No parent references." />
            </InspectorSection>
            <InspectorSection title="Indexes / Unique Constraints">
              <ConstraintList
                indexes={selectedTable.indexes}
                uniqueConstraints={selectedTable.uniqueConstraints}
                foreignKeyConstraints={selectedTable.foreignKeyConstraints}
              />
            </InspectorSection>
          </>
        ) : (
          <div className="text-sm text-slate-500">No table selected.</div>
        )}
      </div>
    </aside>
  );
}

function RelationDetail({ relation }: { relation: SchemaRelation }) {
  const cardinality = getRelationCardinality(relation.relationKind);
  return (
    <section className="rounded border border-teal-200 bg-teal-50 p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="text-sm font-semibold text-teal-900">Selected Relation</div>
        <Pill
          label={`${cardinality.parentLabel}:${cardinality.childLabel}`}
          tone="teal"
        />
      </div>
      <div className="grid gap-1 text-xs text-teal-950">
        <div className="text-teal-700">Parent key</div>
        <div className="font-mono">
          {relation.sourceTable}.{relation.sourceColumn}
        </div>
        <div className="text-teal-700">Referenced by child FK</div>
        <div className="font-mono">
          {relation.targetTable}.{relation.targetColumn}
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          <Pill label={formatRelationKind(relation.relationKind)} tone="teal" />
          <Pill
            label={cardinality.childIsOptional ? "OPTIONAL CHILD" : "REQUIRED CHILD"}
            tone="teal"
          />
        </div>
        <div className="mt-1 text-teal-700">{relation.constraintName}</div>
      </div>
    </section>
  );
}

function ColumnDetail({ column }: { column: SchemaColumn }) {
  return (
    <div className="border-t border-slate-200 py-2 text-xs">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-semibold text-slate-900">{column.name}</div>
          <div className="mt-0.5 truncate text-slate-500">{column.type}</div>
        </div>
        <div className="flex flex-wrap justify-end gap-1">
          {column.primaryKey ? <Pill label="PK" /> : null}
          {column.foreignKeys.length ? <Pill label="FK" /> : null}
          {column.unique ? <Pill label="UQ" /> : null}
          {column.index ? <Pill label="IX" /> : null}
          <Pill label={column.nullable ? "NULL" : "NOT NULL"} />
        </div>
      </div>
      {column.default ? (
        <div className="mt-1 truncate text-slate-500">default {column.default}</div>
      ) : null}
      {column.foreignKeys.length ? (
        <div className="mt-1 text-slate-500">FK to {column.foreignKeys.join(", ")}</div>
      ) : null}
      {column.constraintNames.length ? (
        <div className="mt-1 text-slate-400">{column.constraintNames.join(", ")}</div>
      ) : null}
    </div>
  );
}

function RelationList({
  relations,
  emptyLabel,
}: {
  relations: SchemaRelation[];
  emptyLabel: string;
}) {
  if (!relations.length) {
    return <div className="text-xs text-slate-500">{emptyLabel}</div>;
  }
  return (
    <div className="grid gap-2">
      {relations.map((relation) => {
        const cardinality = getRelationCardinality(relation.relationKind);
        return (
          <div key={relation.id} className="rounded border border-slate-200 p-2 text-xs">
            <div className="text-slate-500">Parent key</div>
            <div className="font-mono text-slate-900">
              {relation.sourceTable}.{relation.sourceColumn}
            </div>
            <div className="mt-1 text-slate-500">Child FK</div>
            <div className="font-mono text-slate-900">
              {relation.targetTable}.{relation.targetColumn}
            </div>
            <div className="mt-2 flex flex-wrap gap-1">
              <Pill label={`${cardinality.parentLabel}:${cardinality.childLabel}`} />
              <Pill label={formatRelationKind(relation.relationKind)} />
              <Pill label={cardinality.childIsOptional ? "OPTIONAL" : "REQUIRED"} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ConstraintList({
  indexes,
  uniqueConstraints,
  foreignKeyConstraints,
}: {
  indexes: SchemaIndex[];
  uniqueConstraints: SchemaUniqueConstraint[];
  foreignKeyConstraints: SchemaForeignKeyConstraint[];
}) {
  const hasAny = indexes.length || uniqueConstraints.length || foreignKeyConstraints.length;
  if (!hasAny) {
    return <div className="text-xs text-slate-500">No table constraints.</div>;
  }
  return (
    <div className="grid gap-2">
      {uniqueConstraints.map((constraint) => (
        <ConstraintItem
          key={constraint.name}
          label="Unique"
          name={constraint.name}
          columns={constraint.columnNames}
        />
      ))}
      {indexes.map((index) => (
        <ConstraintItem
          key={index.name}
          label={index.unique ? "Unique index" : "Index"}
          name={index.name}
          columns={index.columnNames}
        />
      ))}
      {foreignKeyConstraints.map((constraint) => (
        <ConstraintItem
          key={constraint.name}
          label="Foreign key"
          name={constraint.name}
          columns={constraint.columnNames}
          target={`${constraint.targetTable}(${constraint.targetColumnNames.join(", ")})`}
        />
      ))}
    </div>
  );
}

function ConstraintItem({
  label,
  name,
  columns,
  target,
}: {
  label: string;
  name: string;
  columns: string[];
  target?: string;
}) {
  return (
    <div className="rounded border border-slate-200 p-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-slate-700">{label}</span>
        <Pill label={columns.join(", ")} />
      </div>
      <div className="mt-1 truncate font-mono text-slate-500">{name}</div>
      {target ? <div className="mt-1 truncate text-slate-500">to {target}</div> : null}
    </div>
  );
}

function InspectorSection({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function Pill({ label, tone = "slate" }: { label: string; tone?: "slate" | "teal" }) {
  const className =
    tone === "teal"
      ? "bg-teal-100 text-teal-800"
      : "bg-slate-100 text-slate-600";
  return <span className={`rounded px-1.5 py-0.5 text-[11px] ${className}`}>{label}</span>;
}

function formatRelationKind(value: SchemaRelation["relationKind"]) {
  return value.replaceAll("_", " ");
}
