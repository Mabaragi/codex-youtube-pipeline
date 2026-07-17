"use client";

import dynamic from "next/dynamic";

import { PageHeader } from "@/components/page-header";
import { Panel } from "@/components/ui/panel";
import type { SchemaGraph } from "@/features/observability/api";
import { useSchemaGraph } from "@/features/observability/api";

const SchemaGraphView = dynamic(() => import("@/components/schema-graph"), { ssr: false, loading: () => <p className="p-8 text-sm text-[var(--muted)]">스키마 그래프 로딩 중…</p> });

export function SchemaConsole({ initialData }: { initialData: SchemaGraph | null }) { const query = useSchemaGraph(initialData); return <><PageHeader eyebrow="시스템" heading="Schema graph" description="현재 PostgreSQL 테이블, 컬럼, 제약 조건과 관계를 읽기 전용으로 탐색합니다." /><Panel.Root><Panel.Header><Panel.HeadingGroup><Panel.Title>Database schema</Panel.Title><Panel.Description>{query.data?.tables.length ?? 0} tables · {query.data?.relations.length ?? 0} relations</Panel.Description></Panel.HeadingGroup></Panel.Header>{query.data ? <SchemaGraphView graph={query.data} /> : <p role="status" className="p-8 text-sm text-[var(--muted)]">불러오는 중…</p>}</Panel.Root></>; }
