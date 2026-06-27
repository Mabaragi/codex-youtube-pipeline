import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PageHeader } from "../page-header";

describe("PageHeader", () => {
  it("renders optional description, meta, and actions", () => {
    render(
      <PageHeader
        title="Jobs"
        description="Inspect pipeline steps."
        meta={<span>50 rows</span>}
        actions={<button type="button">Retry</button>}
      />,
    );

    expect(screen.getByRole("heading", { name: "Jobs" })).toBeTruthy();
    expect(screen.getByText("Inspect pipeline steps.")).toBeTruthy();
    expect(screen.getByText("50 rows")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });
});
