import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "../status-badge";

describe("StatusBadge", () => {
  it("renders the provided status", () => {
    render(<StatusBadge status="succeeded" />);

    expect(screen.getByText("succeeded")).toBeTruthy();
  });

  it("maps operational statuses to stable tones", () => {
    const { rerender } = render(<StatusBadge status="ready" />);

    expect(screen.getByText("ready").className).toContain("ops-status-info");

    rerender(<StatusBadge status="active" />);
    expect(screen.getByText("active").className).toContain("ops-status-ok");

    rerender(<StatusBadge status="skipped" />);
    expect(screen.getByText("skipped").className).toContain("ops-status-neutral");
  });
});
