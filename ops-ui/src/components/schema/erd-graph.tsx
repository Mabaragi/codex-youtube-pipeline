"use client";

import ELK from "elkjs/lib/elk.bundled.js";
import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  applyNodeChanges,
  type Edge,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { OpsSchemaGraph, OpsSchemaTable } from "@/lib/types";
import { useOpsStore } from "@/store/use-ops-store";

type SchemaRelation = OpsSchemaGraph["relations"][number];

type TableNodeData = {
  table: OpsSchemaTable;
  selected: boolean;
  onSelect: (tableId: string) => void;
};

const nodeTypes = {
  table: TableNode,
};

const EMPTY_POSITION = { x: 0, y: 0 };

export function ErdGraph({ graph }: { graph: OpsSchemaGraph }) {
  const selectedTableId = useOpsStore((state) => state.selectedSchemaTableId);
  const setSelectedTableId = useOpsStore((state) => state.setSelectedSchemaTableId);
  const setSchemaNodePosition = useOpsStore((state) => state.setSchemaNodePosition);
  const setSchemaNodePositions = useOpsStore((state) => state.setSchemaNodePositions);
  const resetSchemaNodePositions = useOpsStore((state) => state.resetSchemaNodePositions);
  const [nodes, setNodes] = useState<Node<TableNodeData>[]>([]);
  const [query, setQuery] = useState("");
  const [layoutVersion, setLayoutVersion] = useState(0);

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

  const visibleRelations = useMemo(() => {
    const visibleIds = new Set(filteredTables.map((table) => table.id));
    return graph.relations.filter(
      (relation) =>
        visibleIds.has(relation.sourceTable) && visibleIds.has(relation.targetTable),
    );
  }, [filteredTables, graph.relations]);

  const edges = useMemo(
    () => buildEdges(visibleRelations, selectedTableId),
    [selectedTableId, visibleRelations],
  );
  const flowNodes = useMemo(
    () =>
      nodes.map((node) => ({
        ...node,
        data: {
          ...node.data,
          selected: node.id === selectedTableId,
        },
      })),
    [nodes, selectedTableId],
  );

  useEffect(() => {
    let canceled = false;
    async function layout() {
      const layoutPositions = await calculateLayoutPositions(filteredTables, visibleRelations);
      if (canceled) {
        return;
      }
      const savedPositions = useOpsStore.getState().schemaNodePositions;
      const currentSelectedTableId = useOpsStore.getState().selectedSchemaTableId;
      setNodes(
        filteredTables.map((table) => ({
          id: table.id,
          type: "table",
          position: savedPositions[table.id] ?? layoutPositions[table.id] ?? EMPTY_POSITION,
          data: {
            table,
            selected: table.id === currentSelectedTableId,
            onSelect: setSelectedTableId,
          },
        })),
      );
    }
    void layout();
    return () => {
      canceled = true;
    };
  }, [filteredTables, layoutVersion, setSelectedTableId, visibleRelations]);

  const onNodesChange = useCallback(
    (changes: NodeChange<Node<TableNodeData>>[]) => {
      setNodes((currentNodes) => applyNodeChanges(changes, currentNodes));
      for (const change of changes) {
        if (change.type === "position" && change.position && !change.dragging) {
          setSchemaNodePosition(change.id, change.position);
        }
      }
    },
    [setSchemaNodePosition],
  );

  const applyAutoLayout = useCallback(async () => {
    const layoutPositions = await calculateLayoutPositions(filteredTables, visibleRelations);
    const currentPositions = useOpsStore.getState().schemaNodePositions;
    setSchemaNodePositions({
      ...currentPositions,
      ...layoutPositions,
    });
    setNodes(
      filteredTables.map((table) => ({
        id: table.id,
        type: "table",
        position: layoutPositions[table.id] ?? EMPTY_POSITION,
        data: {
          table,
          selected: table.id === selectedTableId,
          onSelect: setSelectedTableId,
        },
      })),
    );
  }, [
    filteredTables,
    selectedTableId,
    setSchemaNodePositions,
    setSelectedTableId,
    visibleRelations,
  ]);

  const resetLayout = useCallback(() => {
    resetSchemaNodePositions();
    setLayoutVersion((current) => current + 1);
  }, [resetSchemaNodePositions]);

  return (
    <div className="ops-panel min-h-[720px] overflow-hidden">
      <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 p-3">
        <input
          className="ops-input w-full max-w-sm"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search table or column"
        />
        <button type="button" className="ops-button" onClick={applyAutoLayout}>
          Auto layout
        </button>
        <button type="button" className="ops-button" onClick={resetLayout}>
          Reset layout
        </button>
      </div>
      <div className="h-[670px]">
        <ReactFlow
          nodes={flowNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
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

async function calculateLayoutPositions(
  tables: OpsSchemaTable[],
  relations: SchemaRelation[],
) {
  const elk = new ELK();
  const layouted = await elk.layout({
    id: "root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.spacing.nodeNode": "80",
      "elk.layered.spacing.nodeNodeBetweenLayers": "100",
    },
    children: tables.map((table) => ({
      id: table.id,
      width: 300,
      height: Math.max(120, 48 + table.columns.length * 26),
    })),
    edges: relations.map((relation) => ({
      id: relation.id,
      sources: [relation.sourceTable],
      targets: [relation.targetTable],
    })),
  });
  return Object.fromEntries(
    layouted.children?.map((child) => [
      child.id,
      { x: child.x ?? 0, y: child.y ?? 0 },
    ]) ?? [],
  );
}

function buildEdges(relations: SchemaRelation[], selectedTableId: string | null): Edge[] {
  return relations.map((relation) => ({
    id: relation.id,
    source: relation.sourceTable,
    target: relation.targetTable,
    label: `${relation.sourceColumn} -> ${relation.targetColumn}`,
    animated:
      relation.sourceTable === selectedTableId || relation.targetTable === selectedTableId,
    style: {
      stroke:
        relation.sourceTable === selectedTableId || relation.targetTable === selectedTableId
          ? "var(--accent)"
          : "#8da0b3",
    },
  }));
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
