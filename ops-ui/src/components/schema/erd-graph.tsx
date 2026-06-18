"use client";

import ELK from "elkjs/lib/elk.bundled.js";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { useEffect, useMemo, useState } from "react";
import type { OpsSchemaGraph, OpsSchemaTable } from "@/lib/types";
import { useOpsStore } from "@/store/use-ops-store";

type TableNodeData = {
  table: OpsSchemaTable;
  selected: boolean;
  onSelect: (tableId: string) => void;
};

const nodeTypes = {
  table: TableNode,
};

export function ErdGraph({ graph }: { graph: OpsSchemaGraph }) {
  const selectedTableId = useOpsStore((state) => state.selectedSchemaTableId);
  const setSelectedTableId = useOpsStore((state) => state.setSelectedSchemaTableId);
  const [nodes, setNodes] = useState<Node<TableNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [query, setQuery] = useState("");

  const filteredTables = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    if (!normalized) {
      return graph.tables;
    }
    return graph.tables.filter(
      (table) =>
        table.name.toLowerCase().includes(normalized) ||
        table.columns.some((column) => column.name.toLowerCase().includes(normalized)),
    );
  }, [graph.tables, query]);

  useEffect(() => {
    let canceled = false;
    async function layout() {
      const visibleIds = new Set(filteredTables.map((table) => table.id));
      const elk = new ELK();
      const elkGraph = {
        id: "root",
        layoutOptions: {
          "elk.algorithm": "layered",
          "elk.direction": "RIGHT",
          "elk.spacing.nodeNode": "80",
          "elk.layered.spacing.nodeNodeBetweenLayers": "100",
        },
        children: filteredTables.map((table) => ({
          id: table.id,
          width: 300,
          height: Math.max(120, 48 + table.columns.length * 26),
        })),
        edges: graph.relations
          .filter(
            (relation) =>
              visibleIds.has(relation.sourceTable) && visibleIds.has(relation.targetTable),
          )
          .map((relation) => ({
            id: relation.id,
            sources: [relation.sourceTable],
            targets: [relation.targetTable],
          })),
      };
      const layouted = await elk.layout(elkGraph);
      if (canceled) {
        return;
      }
      const childrenById = new Map(layouted.children?.map((child) => [child.id, child]));
      setNodes(
        filteredTables.map((table) => {
          const child = childrenById.get(table.id);
          return {
            id: table.id,
            type: "table",
            position: { x: child?.x ?? 0, y: child?.y ?? 0 },
            data: {
              table,
              selected: table.id === selectedTableId,
              onSelect: setSelectedTableId,
            },
          };
        }),
      );
      setEdges(
        graph.relations
          .filter(
            (relation) =>
              visibleIds.has(relation.sourceTable) && visibleIds.has(relation.targetTable),
          )
          .map((relation) => ({
            id: relation.id,
            source: relation.sourceTable,
            target: relation.targetTable,
            label: `${relation.sourceColumn} -> ${relation.targetColumn}`,
            animated:
              relation.sourceTable === selectedTableId ||
              relation.targetTable === selectedTableId,
            style: {
              stroke:
                relation.sourceTable === selectedTableId ||
                relation.targetTable === selectedTableId
                  ? "var(--accent)"
                  : "#8da0b3",
            },
          })),
      );
    }
    void layout();
    return () => {
      canceled = true;
    };
  }, [filteredTables, graph.relations, selectedTableId, setSelectedTableId]);

  return (
    <div className="ops-panel min-h-[720px] overflow-hidden">
      <div className="border-b border-slate-200 p-3">
        <input
          className="ops-input w-full max-w-sm"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search table or column"
        />
      </div>
      <div className="h-[670px]">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          minZoom={0.15}
          maxZoom={1.4}
        >
          <Background />
          <MiniMap pannable zoomable />
          <Controls />
        </ReactFlow>
      </div>
    </div>
  );
}

function TableNode({ data }: NodeProps<Node<TableNodeData>>) {
  const { table, selected, onSelect } = data;
  return (
    <button
      type="button"
      onClick={() => onSelect(table.id)}
      className={`w-[300px] border bg-white text-left shadow-sm ${
        selected ? "border-[color:var(--accent)]" : "border-slate-300"
      }`}
    >
      <Handle type="target" position={Position.Left} />
      <div className="bg-slate-800 px-3 py-2 text-sm font-semibold text-white">
        {table.name}
      </div>
      <div className="max-h-[360px] overflow-hidden">
        {table.columns.map((column) => (
          <div
            key={column.id}
            className="grid grid-cols-[minmax(0,1fr)_96px] gap-2 border-t border-slate-200 px-3 py-1.5 text-xs"
          >
            <span className="truncate font-semibold">{column.name}</span>
            <span className="truncate text-right text-slate-500">{column.type}</span>
          </div>
        ))}
      </div>
      <Handle type="source" position={Position.Right} />
    </button>
  );
}
