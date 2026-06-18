"use client";

import ELK from "elkjs/lib/elk.bundled.js";
import {
  Background,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  applyNodeChanges,
  getSmoothStepPath,
  type Edge,
  type EdgeProps,
  type EdgeTypes,
  type Node,
  type NodeChange,
  type NodeProps,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { OpsSchemaGraph, OpsSchemaTable } from "@/lib/types";
import { useOpsStore } from "@/store/use-ops-store";
import {
  estimateTableNodeHeight,
  getRelationCardinality,
  getTableGroup,
  type RelationCardinality,
  type SchemaTableGroup,
} from "./schema-display";

type SchemaRelation = OpsSchemaGraph["relations"][number];
type SchemaColumn = OpsSchemaTable["columns"][number];

type ErdRelationEdgeData = {
  relation: SchemaRelation;
  isConnected: boolean;
  isSelected: boolean;
};

type TableNodeData = {
  table: OpsSchemaTable;
  group: SchemaTableGroup;
  selected: boolean;
  relationCount: number;
  onSelect: (tableId: string) => void;
};

const nodeTypes = {
  table: TableNode,
};

const edgeTypes: EdgeTypes = {
  erdRelation: ErdRelationEdge,
};

const EMPTY_POSITION = { x: 0, y: 0 };
const TABLE_WIDTH = 340;

const GROUP_LABELS: Record<SchemaTableGroup, string> = {
  core: "Core",
  processing: "Processing",
  artifacts: "Artifacts",
  support: "Support",
};

const GROUP_CLASS_NAMES: Record<SchemaTableGroup, string> = {
  core: "border-sky-300 bg-sky-50 text-sky-800",
  processing: "border-violet-300 bg-violet-50 text-violet-800",
  artifacts: "border-emerald-300 bg-emerald-50 text-emerald-800",
  support: "border-slate-300 bg-slate-50 text-slate-700",
};

export function ErdGraph({
  graph,
  selectedRelationId,
  onSelectRelation,
}: {
  graph: OpsSchemaGraph;
  selectedRelationId: string | null;
  onSelectRelation: (relationId: string | null) => void;
}) {
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
    const tables = normalized
      ? graph.tables.filter(
          (table) =>
            table.name.toLowerCase().includes(normalized) ||
            table.columns.some((column) => column.name.toLowerCase().includes(normalized)),
        )
      : graph.tables;
    return [...tables].sort(compareTablesByGroup);
  }, [graph.tables, query]);

  const visibleRelations = useMemo(() => {
    const visibleIds = new Set(filteredTables.map((table) => table.id));
    return graph.relations.filter(
      (relation) =>
        visibleIds.has(relation.sourceTable) && visibleIds.has(relation.targetTable),
    );
  }, [filteredTables, graph.relations]);

  const relationCountByTable = useMemo(() => {
    const counts = new Map<string, number>();
    for (const relation of graph.relations) {
      counts.set(relation.sourceTable, (counts.get(relation.sourceTable) ?? 0) + 1);
      counts.set(relation.targetTable, (counts.get(relation.targetTable) ?? 0) + 1);
    }
    return counts;
  }, [graph.relations]);

  const edges = useMemo(
    () => buildEdges(visibleRelations, selectedTableId, selectedRelationId),
    [selectedRelationId, selectedTableId, visibleRelations],
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
            group: getTableGroup(table.name),
            selected: table.id === currentSelectedTableId,
            relationCount: relationCountByTable.get(table.id) ?? 0,
            onSelect: (tableId) => {
              onSelectRelation(null);
              setSelectedTableId(tableId);
            },
          },
        })),
      );
    }
    void layout();
    return () => {
      canceled = true;
    };
  }, [
    filteredTables,
    layoutVersion,
    onSelectRelation,
    relationCountByTable,
    setSelectedTableId,
    visibleRelations,
  ]);

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
          group: getTableGroup(table.name),
          selected: table.id === selectedTableId,
          relationCount: relationCountByTable.get(table.id) ?? 0,
          onSelect: (tableId) => {
            onSelectRelation(null);
            setSelectedTableId(tableId);
          },
        },
      })),
    );
  }, [
    filteredTables,
    onSelectRelation,
    relationCountByTable,
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
        <div className="ml-auto flex flex-wrap gap-1 text-xs">
          {(["core", "processing", "artifacts", "support"] as const).map((group) => (
            <span
              key={group}
              className={`rounded border px-2 py-1 ${GROUP_CLASS_NAMES[group]}`}
            >
              {GROUP_LABELS[group]}
            </span>
          ))}
        </div>
      </div>
      <div className="h-[670px]">
        <ReactFlow
          nodes={flowNodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgeClick={(_, edge) => onSelectRelation(edge.id)}
          fitView
          fitViewOptions={{ padding: 0.08 }}
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

function compareTablesByGroup(first: OpsSchemaTable, second: OpsSchemaTable) {
  const order: Record<SchemaTableGroup, number> = {
    core: 0,
    processing: 1,
    artifacts: 2,
    support: 3,
  };
  return (
    order[getTableGroup(first.name)] - order[getTableGroup(second.name)] ||
    first.name.localeCompare(second.name)
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
      "elk.spacing.nodeNode": "96",
      "elk.layered.spacing.nodeNodeBetweenLayers": "128",
    },
    children: tables.map((table) => ({
      id: table.id,
      width: TABLE_WIDTH,
      height: estimateTableNodeHeight(table),
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

function buildEdges(
  relations: SchemaRelation[],
  selectedTableId: string | null,
  selectedRelationId: string | null,
): Edge<ErdRelationEdgeData>[] {
  return relations.map((relation) => {
    const isConnected =
      relation.sourceTable === selectedTableId || relation.targetTable === selectedTableId;
    const isSelected = relation.id === selectedRelationId;
    return {
      id: relation.id,
      type: "erdRelation",
      source: relation.sourceTable,
      target: relation.targetTable,
      sourceHandle: relationHandleId("source", relation.sourceColumn),
      targetHandle: relationHandleId("target", relation.targetColumn),
      label: `${relation.sourceColumn} -> ${relation.targetColumn}`,
      data: {
        relation,
        isConnected,
        isSelected,
      },
      style: {
        stroke: isSelected ? "#0f766e" : isConnected ? "var(--accent)" : "#8da0b3",
        strokeWidth: isSelected ? 2.5 : isConnected ? 2 : 1.25,
      },
      interactionWidth: 28,
    };
  });
}

function relationHandleId(type: "source" | "target", columnName: string) {
  return `${type}:${columnName}`;
}

function ErdRelationEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}: EdgeProps) {
  const edgeData = data as ErdRelationEdgeData | undefined;
  const relation = edgeData?.relation;
  const cardinality = relation
    ? getRelationCardinality(relation.relationKind)
    : null;
  const isSelected = edgeData?.isSelected ?? false;
  const isConnected = edgeData?.isConnected ?? false;
  const stroke = isSelected ? "#0f766e" : isConnected ? "var(--accent)" : "#64748b";
  const strokeWidth = isSelected ? 2.5 : isConnected ? 2 : 1.35;
  const [edgePath, labelX, labelY] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 2,
    offset: 28,
  });

  return (
    <>
      <BaseEdge
        id={id}
        path={edgePath}
        interactionWidth={28}
        style={{
          stroke,
          strokeWidth,
          fill: "none",
        }}
        vectorEffect="non-scaling-stroke"
      />
      {cardinality ? (
        <>
          <ExactOneMarker
            x={sourceX}
            y={sourceY}
            position={sourcePosition}
            stroke={stroke}
          />
          <ChildCardinalityMarker
            x={targetX}
            y={targetY}
            position={targetPosition}
            cardinality={cardinality}
            stroke={stroke}
          />
        </>
      ) : null}
      {relation && cardinality ? (
        <EdgeLabelRenderer>
          <div
            className={`rounded border bg-white/95 px-1.5 py-0.5 font-mono text-[10px] shadow-sm ${
              isSelected || isConnected
                ? "border-teal-200 text-slate-900"
                : "border-slate-200 text-slate-500"
            }`}
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`,
              pointerEvents: "none",
            }}
          >
            {cardinality.parentLabel}:{cardinality.childLabel} / {relation.targetColumn}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  );
}

function ExactOneMarker({
  x,
  y,
  position,
  stroke,
}: {
  x: number;
  y: number;
  position: Position;
  stroke: string;
}) {
  return (
    <g
      data-testid="erd-parent-cardinality"
      stroke={stroke}
      strokeLinecap="round"
      strokeWidth={2}
      vectorEffect="non-scaling-stroke"
    >
      <EndpointBar x={x} y={y} position={position} distance={7} />
      <EndpointBar x={x} y={y} position={position} distance={13} />
    </g>
  );
}

function ChildCardinalityMarker({
  x,
  y,
  position,
  cardinality,
  stroke,
}: {
  x: number;
  y: number;
  position: Position;
  cardinality: RelationCardinality;
  stroke: string;
}) {
  return (
    <g
      data-cardinality={cardinality.childLabel}
      data-testid="erd-child-cardinality"
      stroke={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth={2}
    >
      {cardinality.childIsOptional ? (
        <EndpointCircle
          x={x}
          y={y}
          position={position}
          distance={cardinality.childIsMany ? 28 : 19}
        />
      ) : cardinality.childIsMany ? (
        <EndpointBar x={x} y={y} position={position} distance={28} />
      ) : null}
      {cardinality.childIsMany ? (
        <CrowFoot x={x} y={y} position={position} />
      ) : (
        <>
          <EndpointBar x={x} y={y} position={position} distance={7} />
          {!cardinality.childIsOptional ? (
            <EndpointBar x={x} y={y} position={position} distance={13} />
          ) : null}
        </>
      )}
    </g>
  );
}

function EndpointBar({
  x,
  y,
  position,
  distance,
}: {
  x: number;
  y: number;
  position: Position;
  distance: number;
}) {
  const center = endpointPoint(x, y, position, distance);
  if (position === Position.Left || position === Position.Right) {
    return (
      <path
        d={`M ${center.x} ${center.y - 8} V ${center.y + 8}`}
        vectorEffect="non-scaling-stroke"
      />
    );
  }
  return (
    <path
      d={`M ${center.x - 8} ${center.y} H ${center.x + 8}`}
      vectorEffect="non-scaling-stroke"
    />
  );
}

function EndpointCircle({
  x,
  y,
  position,
  distance,
}: {
  x: number;
  y: number;
  position: Position;
  distance: number;
}) {
  const center = endpointPoint(x, y, position, distance);
  return (
    <circle
      cx={center.x}
      cy={center.y}
      r={5}
      fill="#ffffff"
      vectorEffect="non-scaling-stroke"
    />
  );
}

function CrowFoot({
  x,
  y,
  position,
}: {
  x: number;
  y: number;
  position: Position;
}) {
  const base = endpointPoint(x, y, position, 19);
  const centerTip = endpointPoint(x, y, position, 4);
  if (position === Position.Left || position === Position.Right) {
    return (
      <>
        <path
          d={`M ${base.x} ${base.y} L ${centerTip.x} ${centerTip.y - 9}`}
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={`M ${base.x} ${base.y} L ${centerTip.x} ${centerTip.y}`}
          vectorEffect="non-scaling-stroke"
        />
        <path
          d={`M ${base.x} ${base.y} L ${centerTip.x} ${centerTip.y + 9}`}
          vectorEffect="non-scaling-stroke"
        />
      </>
    );
  }
  return (
    <>
      <path
        d={`M ${base.x} ${base.y} L ${centerTip.x - 9} ${centerTip.y}`}
        vectorEffect="non-scaling-stroke"
      />
      <path
        d={`M ${base.x} ${base.y} L ${centerTip.x} ${centerTip.y}`}
        vectorEffect="non-scaling-stroke"
      />
      <path
        d={`M ${base.x} ${base.y} L ${centerTip.x + 9} ${centerTip.y}`}
        vectorEffect="non-scaling-stroke"
      />
    </>
  );
}

function endpointPoint(x: number, y: number, position: Position, distance: number) {
  if (position === Position.Left) {
    return { x: x - distance, y };
  }
  if (position === Position.Right) {
    return { x: x + distance, y };
  }
  if (position === Position.Top) {
    return { x, y: y - distance };
  }
  return { x, y: y + distance };
}

function TableNode({ data }: NodeProps<Node<TableNodeData>>) {
  const { table, group, selected, relationCount, onSelect } = data;
  return (
    <button
      type="button"
      onClick={() => onSelect(table.id)}
      className={`w-[340px] overflow-hidden border bg-white text-left shadow-sm ${
        selected ? "border-[color:var(--accent)] ring-2 ring-sky-100" : "border-slate-300"
      }`}
    >
      <div className="flex items-start justify-between gap-3 bg-slate-900 px-3 py-2 text-white">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{table.name}</div>
          <div className="mt-1 text-xs text-slate-300">
            {table.columns.length} columns · {relationCount} relations
          </div>
        </div>
        <span className={`rounded border px-2 py-0.5 text-[11px] ${GROUP_CLASS_NAMES[group]}`}>
          {GROUP_LABELS[group]}
        </span>
      </div>
      <div>
        {table.columns.map((column) => (
          <ColumnRow key={column.id} column={column} />
        ))}
      </div>
    </button>
  );
}

function ColumnRow({ column }: { column: SchemaColumn }) {
  return (
    <div className="relative grid grid-cols-[minmax(0,1fr)_112px] gap-2 border-t border-slate-200 px-3 py-1.5 text-xs">
      <Handle
        id={relationHandleId("target", column.name)}
        type="target"
        position={Position.Left}
        isConnectable={false}
        className="!h-2 !w-2 !border-0 !bg-transparent !opacity-0"
      />
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-1">
          <span className="truncate font-semibold text-slate-900">{column.name}</span>
          <ColumnBadges column={column} />
        </div>
        {column.default ? (
          <div className="mt-0.5 truncate text-[11px] text-slate-500">
            default {column.default}
          </div>
        ) : null}
      </div>
      <div className="min-w-0 text-right">
        <div className="truncate text-slate-600">{column.type}</div>
        <div className="text-[11px] text-slate-400">
          {column.nullable ? "NULL" : "NOT NULL"}
        </div>
      </div>
      <Handle
        id={relationHandleId("source", column.name)}
        type="source"
        position={Position.Right}
        isConnectable={false}
        className="!h-2 !w-2 !border-0 !bg-transparent !opacity-0"
      />
    </div>
  );
}

function ColumnBadges({ column }: { column: SchemaColumn }) {
  const badges = [
    column.primaryKey ? "PK" : null,
    column.foreignKeys.length ? "FK" : null,
    column.unique ? "UQ" : null,
    column.index ? "IX" : null,
  ].filter(Boolean);
  return (
    <>
      {badges.map((badge) => (
        <span
          key={badge}
          className="rounded bg-slate-100 px-1 py-0.5 text-[10px] font-semibold text-slate-600"
        >
          {badge}
        </span>
      ))}
    </>
  );
}
