import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "../status-badge";

describe("StatusBadge", () => {
  it("renders the provided status", () => {
    render(<StatusBadge status="succeeded" />);

    expect(screen.getByText("succeeded")).toBeTruthy();
  });
});
