"use client";

import { Background, Controls, ReactFlow, type Edge, type Node, useEdgesState, useNodesState } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import ELK from "elkjs/lib/elk.bundled.js";
import { useEffect, useMemo } from "react";

import type { SchemaGraph } from "@/features/observability/api";

export default function SchemaGraphView({ graph }: { graph: SchemaGraph }) {
  const initialNodes = useMemo<Node[]>(() => graph.tables.map((table, index) => ({ id: table.id, position: { x: (index % 5) * 260, y: Math.floor(index / 5) * 240 }, data: { label: <div className="min-w-48 text-left"><strong className="font-mono text-xs" translate="no">{table.name}</strong><div className="mt-2 grid gap-1 border-t pt-2">{table.columns.slice(0, 14).map((column) => <span key={column.name} className="font-mono text-[10px]" translate="no">{column.name} <em className="not-italic text-[var(--muted)]">{column.type}</em></span>)}</div></div> }, style: { width: 220, borderRadius: 8, border: "1px solid var(--line-strong)", background: "var(--surface-raised)", color: "var(--foreground)", padding: 12 } })), [graph.tables]);
  const initialEdges = useMemo<Edge[]>(() => graph.relations.map((relation) => ({ id: relation.id, source: relation.sourceTable, target: relation.targetTable, label: relation.constraintName, type: "smoothstep" })), [graph.relations]);
  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes); const [edges, , onEdgesChange] = useEdgesState(initialEdges);
  useEffect(() => { const elk = new ELK(); void elk.layout({ id: "root", layoutOptions: { "elk.algorithm": "layered", "elk.direction": "RIGHT", "elk.spacing.nodeNode": "45" }, children: initialNodes.map((node) => ({ id: node.id, width: 220, height: 220 })), edges: initialEdges.map((edge) => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })) }).then((layout) => { const positions = new Map(layout.children?.map((child) => [child.id, child])); setNodes((current) => current.map((node) => ({ ...node, position: { x: positions.get(node.id)?.x ?? node.position.x, y: positions.get(node.id)?.y ?? node.position.y } }))); }); }, [initialEdges, initialNodes, setNodes]);
  return <div className="h-[70dvh] min-h-[32rem]" role="img" aria-label={`${graph.tables.length}개 테이블과 ${graph.relations.length}개 관계의 스키마 그래프`}><ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} fitView minZoom={0.1} maxZoom={1.5}><Background /><Controls /></ReactFlow></div>;
}
