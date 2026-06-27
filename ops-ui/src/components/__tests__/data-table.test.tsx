import type { ColumnDef } from "@tanstack/react-table";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { DataTable } from "../data-table";

type Row = {
  id: number;
  label: string;
};

const columns: ColumnDef<Row>[] = [
  { header: "ID", accessorKey: "id" },
  { header: "Label", accessorKey: "label" },
];

describe("DataTable", () => {
  it("renders accessible table metadata and empty state", () => {
    render(
      <DataTable
        ariaLabel="Example rows"
        caption="Rows used by the table test"
        columns={columns}
        data={[]}
      />,
    );

    expect(screen.getByRole("table", { name: "Example rows" })).toBeTruthy();
    expect(screen.getByText("Rows used by the table test")).toBeTruthy();
    expect(screen.getByText("No rows.")).toBeTruthy();
  });
});
