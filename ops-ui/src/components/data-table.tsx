"use client";

import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";

type DataTableProps<TData> = {
  columns: ColumnDef<TData>[];
  data: TData[];
  ariaLabel?: string;
  caption?: string;
  emptyLabel?: string;
};

export function DataTable<TData>({
  columns,
  data,
  ariaLabel,
  caption,
  emptyLabel = "No rows.",
}: DataTableProps<TData>) {
  // TanStack Table intentionally exposes stable table helpers from this hook.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });

  return (
    <div className="ops-panel overflow-x-auto">
      <table aria-label={ariaLabel} className="ops-table">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th key={header.id}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length}>
                <div className="py-6 text-center text-sm text-slate-500">
                  {emptyLabel}
                </div>
              </td>
            </tr>
          ) : (
            table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
