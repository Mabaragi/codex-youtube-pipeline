import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PromptsPage } from "../prompts-page";
import type {
  PromptDetail,
  PromptKey,
  PromptSummary,
  PromptVersion,
} from "@/lib/types";

const mutationMocks = vi.hoisted(() => ({
  createVersion: vi.fn(),
  updateVersion: vi.fn(),
  publishVersion: vi.fn(),
  archiveVersion: vi.fn(),
  invalidateCache: vi.fn(),
}));

const queryMocks = vi.hoisted(() => ({
  prompts: {
    data: [] as PromptSummary[],
    isLoading: false,
    error: null as Error | null,
  },
  details: {} as Partial<Record<PromptKey, PromptDetail>>,
  detailKey: null as PromptKey | null | undefined,
}));

vi.mock("@/lib/queries", () => ({
  usePrompts: () => queryMocks.prompts,
  usePromptDetail: (promptKey: PromptKey | null | undefined) => {
    queryMocks.detailKey = promptKey;
    return {
      data: promptKey ? queryMocks.details[promptKey] : undefined,
      isLoading: false,
      error: null,
    };
  },
  useCreatePromptVersionMutation: () => ({
    mutateAsync: mutationMocks.createVersion,
    isPending: false,
  }),
  useUpdatePromptVersionMutation: () => ({
    mutateAsync: mutationMocks.updateVersion,
    isPending: false,
  }),
  usePublishPromptVersionMutation: () => ({
    mutateAsync: mutationMocks.publishVersion,
    isPending: false,
  }),
  useArchivePromptVersionMutation: () => ({
    mutateAsync: mutationMocks.archiveVersion,
    isPending: false,
  }),
  useInvalidatePromptCacheMutation: () => ({
    mutateAsync: mutationMocks.invalidateCache,
    isPending: false,
  }),
}));

const activeMicro = version({
  id: 2,
  label: "micro-v1",
  promptKey: "micro_event_extract",
  status: "PUBLISHED",
  isActive: true,
  sha: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
});

const draftMicro = version({
  id: 3,
  label: "micro-draft",
  promptKey: "micro_event_extract",
  status: "DRAFT",
  isActive: false,
  sha: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  sourceNote: "draft note",
});

const archivedMicro = version({
  id: 4,
  label: "micro-old",
  promptKey: "micro_event_extract",
  status: "ARCHIVED",
  isActive: false,
  sha: "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
});

const summaries: PromptSummary[] = [
  {
    key: "micro_event_extract",
    active: {
      key: "micro_event_extract",
      versionId: 2,
      versionLabel: "micro-v1",
      body: "first line\nsecond line",
      bodySha256: activeMicro.bodySha256,
      source: "database",
    },
    versionCount: 3,
  },
  {
    key: "timeline_compose",
    active: {
      key: "timeline_compose",
      versionId: null,
      versionLabel: "fallback",
      body: "compose fallback body",
      bodySha256: "dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd",
      source: "fallback",
    },
    versionCount: 0,
  },
  {
    key: "timeline_episode_repair",
    active: {
      key: "timeline_episode_repair",
      versionId: null,
      versionLabel: "fallback",
      body: "repair fallback body",
      bodySha256: "eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
      source: "fallback",
    },
    versionCount: 0,
  },
];

const microDetail: PromptDetail = {
  key: "micro_event_extract",
  active: summaries[0].active,
  versions: [draftMicro, activeMicro, archivedMicro],
};

const timelineDetail: PromptDetail = {
  key: "timeline_compose",
  active: summaries[1].active,
  versions: [],
};

describe("PromptsPage", () => {
  beforeEach(() => {
    queryMocks.prompts.data = summaries;
    queryMocks.prompts.isLoading = false;
    queryMocks.prompts.error = null;
    queryMocks.details = {
      micro_event_extract: microDetail,
      timeline_compose: timelineDetail,
      timeline_episode_repair: {
        key: "timeline_episode_repair",
        active: summaries[2].active,
        versions: [],
      },
    };
    queryMocks.detailKey = null;
    mutationMocks.createVersion.mockReset();
    mutationMocks.updateVersion.mockReset();
    mutationMocks.publishVersion.mockReset();
    mutationMocks.archiveVersion.mockReset();
    mutationMocks.invalidateCache.mockReset();
    mutationMocks.createVersion.mockResolvedValue(draftMicro);
    mutationMocks.updateVersion.mockResolvedValue({
      ...draftMicro,
      sourceNote: "updated note",
    });
    mutationMocks.publishVersion.mockResolvedValue({
      ...draftMicro,
      status: "PUBLISHED",
      isActive: true,
    });
    mutationMocks.archiveVersion.mockResolvedValue({
      ...draftMicro,
      status: "ARCHIVED",
    });
    mutationMocks.invalidateCache.mockResolvedValue({ invalidatedCount: 1 });
  });

  it("renders the three known prompt keys with source and version metadata", () => {
    render(<PromptsPage />);

    expect(screen.getByText("micro_event_extract")).toBeTruthy();
    expect(screen.getByText("timeline_compose")).toBeTruthy();
    expect(screen.getByText("timeline_episode_repair")).toBeTruthy();
    expect(screen.getAllByText("database").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("fallback").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("3 versions")).toBeTruthy();
  });

  it("updates the detail panel when another prompt is selected", async () => {
    render(<PromptsPage />);

    fireEvent.click(screen.getByText("timeline_compose"));

    await waitFor(() => expect(queryMocks.detailKey).toBe("timeline_compose"));
    expect(screen.getByText("Active prompt is currently served from fallback resources.")).toBeTruthy();
  });

  it("creates a draft with version label, body, and source note", async () => {
    render(<PromptsPage />);

    fireEvent.change(screen.getByLabelText("Version label"), {
      target: { value: "micro-v2" },
    });
    fireEvent.change(screen.getByLabelText("Body"), {
      target: { value: "first line\nchanged line" },
    });
    fireEvent.change(screen.getByLabelText("Source note"), {
      target: { value: "ops update" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create draft" }));

    await waitFor(() => expect(mutationMocks.createVersion).toHaveBeenCalledTimes(1));
    expect(mutationMocks.createVersion).toHaveBeenCalledWith({
      promptKey: "micro_event_extract",
      body: {
        versionLabel: "micro-v2",
        body: "first line\nchanged line",
        sourceNote: "ops update",
      },
    });
    expect(screen.getByLabelText("changed line 2")).toBeTruthy();
  });

  it("edits only draft versions and sends a PATCH payload", async () => {
    render(<PromptsPage />);

    const draftRow = screen.getByText("micro-draft").closest("tr");
    expect(draftRow).toBeTruthy();
    fireEvent.click(within(draftRow as HTMLElement).getByRole("button", { name: "Edit" }));
    expect(
      screen.getByText(/Draft body is not returned by the API/),
    ).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Body"), {
      target: { value: "updated draft body" },
    });
    fireEvent.change(screen.getByLabelText("Source note"), {
      target: { value: "updated note" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));

    await waitFor(() => expect(mutationMocks.updateVersion).toHaveBeenCalledTimes(1));
    expect(mutationMocks.updateVersion).toHaveBeenCalledWith({
      promptKey: "micro_event_extract",
      versionId: 3,
      body: {
        body: "updated draft body",
        sourceNote: "updated note",
      },
    });

    fireEvent.click(screen.getByText("micro-old"));
    expect(screen.getByRole("button", { name: "Create draft" })).toBeTruthy();
  });

  it("publishes and archives only after a confirmation dialog", async () => {
    render(<PromptsPage />);

    const draftRow = screen.getByText("micro-draft").closest("tr") as HTMLElement;
    fireEvent.click(within(draftRow).getByRole("button", { name: "Publish" }));

    const publishDialog = screen.getByRole("dialog", {
      name: "Publish Prompt Version",
    });
    expect(within(publishDialog).getByText("micro-v1")).toBeTruthy();
    expect(within(publishDialog).getByText("micro-draft")).toBeTruthy();
    fireEvent.click(within(publishDialog).getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(mutationMocks.publishVersion).toHaveBeenCalledWith({
      promptKey: "micro_event_extract",
      versionId: 3,
    }));

    fireEvent.click(within(draftRow).getByRole("button", { name: "Archive" }));
    const archiveDialog = screen.getByRole("dialog", {
      name: "Archive Prompt Version",
    });
    fireEvent.click(within(archiveDialog).getByRole("button", { name: "Archive" }));

    await waitFor(() => expect(mutationMocks.archiveVersion).toHaveBeenCalledWith({
      promptKey: "micro_event_extract",
      versionId: 3,
    }));
  });

  it("disables active archive and explains the 409 prevention", () => {
    render(<PromptsPage />);

    const versionsTable = screen.getByRole("table", { name: "Prompt versions" });
    const activeVersionButton = within(versionsTable).getByRole("button", {
      name: "micro-v1",
    });
    const activeRow = activeVersionButton.closest("tr") as HTMLElement;
    const archiveButton = within(activeRow).getByRole("button", { name: "Archive" });

    expect((archiveButton as HTMLButtonElement).disabled).toBe(true);
    expect(archiveButton.getAttribute("title")).toBe(
      "Active prompt versions cannot be archived",
    );
    expect(
      screen.getByText(/Active prompt versions cannot be archived/),
    ).toBeTruthy();
  });

  it("invalidates cache and reports the result through a live notice", async () => {
    render(<PromptsPage />);

    fireEvent.click(screen.getByRole("button", { name: "Invalidate cache" }));

    await waitFor(() => expect(mutationMocks.invalidateCache).toHaveBeenCalledWith({
      promptKey: "micro_event_extract",
    }));
    expect(screen.getByText("Invalidated 1 cached prompt entries.")).toBeTruthy();
  });
});

function version({
  id,
  label,
  promptKey,
  status,
  isActive,
  sha,
  sourceNote = null,
}: {
  id: number;
  label: string;
  promptKey: PromptKey;
  status: PromptVersion["status"];
  isActive: boolean;
  sha: string;
  sourceNote?: string | null;
}): PromptVersion {
  return {
    id,
    promptKey,
    versionLabel: label,
    bodySha256: sha,
    status,
    sourceNote,
    createdAt: "2026-06-27T00:00:00Z",
    updatedAt: "2026-06-27T01:00:00Z",
    publishedAt: status === "PUBLISHED" ? "2026-06-27T01:00:00Z" : null,
    archivedAt: status === "ARCHIVED" ? "2026-06-27T02:00:00Z" : null,
    isActive,
  };
}
