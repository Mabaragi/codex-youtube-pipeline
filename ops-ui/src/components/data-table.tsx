"use client";

import {
  flexRender,
  getCoreRowModel,
  type ColumnDef,
  type RowData,
  type Table,
  useReactTable,
} from "@tanstack/react-table";
import { createContext, type ReactNode, use, useMemo } from "react";

import { EmptyState, ErrorNotice, RefreshStatus } from "@/components/async-state";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

interface DataTableState {
  initialLoading: boolean;
  refreshing: boolean;
  placeholder: boolean;
  error: string | null;
}

interface DataTableActions {
  refresh?: () => void;
  next?: () => void;
  previous?: () => void;
}

interface DataTableMeta {
  label: string;
  emptyTitle: string;
  emptyDescription: string;
  canNext: boolean;
  canPrevious: boolean;
}

interface DataTableContextValue {
  table: Table<RowData>;
  state: DataTableState;
  actions: DataTableActions;
  meta: DataTableMeta;
}

const DataTableContext = createContext<DataTableContextValue | null>(null);

function useDataTable(): DataTableContextValue {
  const value = use(DataTableContext);
  if (!value) throw new Error("DataTable components require DataTable.Provider.");
  return value;
}

interface ProviderProps<TData extends RowData> {
  children: ReactNode;
  rows: TData[];
  columns: ColumnDef<TData>[];
  getRowId: (row: TData) => string;
  state?: Partial<DataTableState>;
  actions?: DataTableActions;
  meta: Omit<DataTableMeta, "canNext" | "canPrevious"> & {
    canNext?: boolean;
    canPrevious?: boolean;
  };
}

function Provider<TData extends RowData>({
  children,
  rows,
  columns,
  getRowId,
  state,
  actions,
  meta,
}: ProviderProps<TData>) {
  // TanStack Table intentionally returns an imperative table model.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data: rows,
    columns,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
  });
  const value = useMemo<DataTableContextValue>(
    () => ({
      table: table as Table<RowData>,
      state: {
        initialLoading: state?.initialLoading ?? false,
        refreshing: state?.refreshing ?? false,
        placeholder: state?.placeholder ?? false,
        error: state?.error ?? null,
      },
      actions: actions ?? {},
      meta: {
        ...meta,
        canNext: meta.canNext ?? false,
        canPrevious: meta.canPrevious ?? false,
      },
    }),
    [actions, meta, state, table],
  );
  return <DataTableContext value={value}>{children}</DataTableContext>;
}

function Frame({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div data-slot="data-table" className={cn("ops-panel min-w-0", className)}>
      {children}
    </div>
  );
}

function Toolbar({ children }: { children: ReactNode }) {
  const { state } = useDataTable();
  return (
    <div className="flex min-h-14 flex-wrap items-end justify-between gap-3 border-b px-4 py-3">
      <div className="flex min-w-0 flex-1 flex-wrap items-end gap-2">{children}</div>
      <RefreshStatus refreshing={state.refreshing} />
    </div>
  );
}

function Content() {
  const { table, state, meta } = useDataTable();
  if (state.error && table.getRowModel().rows.length === 0) {
    return <div className="p-4"><ErrorNotice message={state.error} /></div>;
  }
  if (state.initialLoading && table.getRowModel().rows.length === 0) {
    return <div className="p-8 text-center text-sm text-[var(--muted)]" role="status">불러오는 중…</div>;
  }
  if (table.getRowModel().rows.length === 0) {
    return <EmptyState title={meta.emptyTitle} description={meta.emptyDescription} />;
  }
  return (
    <div className="ops-scrollbar overflow-x-auto" aria-busy={state.refreshing}>
      <table className="w-full min-w-[48rem] border-collapse text-left text-[13px]" aria-label={meta.label}>
        <thead className="bg-[var(--surface-muted)] text-xs text-[var(--muted)]">
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id} scope="col" className="border-b px-3 py-2 font-semibold">
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody data-placeholder={state.placeholder || undefined}>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id} className="ops-virtual-row border-b last:border-b-0 hover:bg-[var(--surface-muted)]/70">
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id} className="max-w-[24rem] px-3 py-2.5 align-top">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Pagination() {
  const { state, actions, meta } = useDataTable();
  if (!meta.canNext && !meta.canPrevious) return null;
  return (
    <div className="flex justify-end gap-2 border-t px-4 py-3">
      <Button onClick={actions.previous} disabled={!meta.canPrevious || state.placeholder}>이전</Button>
      <Button onClick={actions.next} disabled={!meta.canNext || state.placeholder}>다음</Button>
    </div>
  );
}

export const DataTable = { Provider, Frame, Toolbar, Content, Pagination };
