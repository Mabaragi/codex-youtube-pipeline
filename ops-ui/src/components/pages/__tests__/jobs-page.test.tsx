import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JobsPage } from "../jobs-page";

describe("JobsPage", () => {
  it("directs legacy job users to unified work items", () => {
    render(<JobsPage />);
    expect(screen.getByText("Work History")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open Work Items" }).getAttribute("href")).toBe("/tasks");
  });
});
