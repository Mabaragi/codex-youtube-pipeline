import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DomainKnowledgePage } from "../domain-knowledge-page";
import type {
  DomainEntry,
  DomainEntryFilters,
  DomainEntryList,
  DomainEntryType,
  Streamer,
} from "@/lib/types";

const routerPush = vi.hoisted(() => vi.fn());
const mutationMocks = vi.hoisted(() => ({
  createEntry: vi.fn(),
  updateEntry: vi.fn(),
  archiveEntry: vi.fn(),
  addAlias: vi.fn(),
  updateAlias: vi.fn(),
  deleteAlias: vi.fn(),
  addStreamer: vi.fn(),
  removeStreamer: vi.fn(),
}));
const queryMocks = vi.hoisted(() => ({
  filters: undefined as DomainEntryFilters | undefined,
  types: {
    data: [] as DomainEntryType[],
    isLoading: false,
    error: null as Error | null,
  },
  streamers: {
    data: [] as Streamer[],
    isLoading: false,
    error: null as Error | null,
  },
  entries: {
    data: undefined as DomainEntryList | undefined,
    isLoading: false,
    error: null as Error | null,
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: routerPush }),
}));

vi.mock("@/lib/queries", () => ({
  useDomainEntryTypes: () => queryMocks.types,
  useStreamers: () => queryMocks.streamers,
  useDomainEntries: (filters: DomainEntryFilters) => {
    queryMocks.filters = filters;
    return queryMocks.entries;
  },
  useCreateDomainEntryMutation: () => ({
    mutateAsync: mutationMocks.createEntry,
    isPending: false,
  }),
  useUpdateDomainEntryMutation: () => ({
    mutateAsync: mutationMocks.updateEntry,
    isPending: false,
  }),
  useArchiveDomainEntryMutation: () => ({
    mutateAsync: mutationMocks.archiveEntry,
    isPending: false,
  }),
  useAddDomainEntryAliasMutation: () => ({
    mutateAsync: mutationMocks.addAlias,
    isPending: false,
  }),
  useUpdateDomainEntryAliasMutation: () => ({
    mutateAsync: mutationMocks.updateAlias,
    isPending: false,
  }),
  useDeleteDomainEntryAliasMutation: () => ({
    mutateAsync: mutationMocks.deleteAlias,
    isPending: false,
  }),
  useAddDomainEntryStreamerMutation: () => ({
    mutateAsync: mutationMocks.addStreamer,
    isPending: false,
  }),
  useRemoveDomainEntryStreamerMutation: () => ({
    mutateAsync: mutationMocks.removeStreamer,
    isPending: false,
  }),
}));

const types: DomainEntryType[] = [
  {
    typeId: 1,
    key: "person",
    label: "Person",
    description: null,
    sortOrder: 10,
    isSystem: true,
    createdAt: "2026-06-23T00:00:00Z",
    updatedAt: "2026-06-23T00:00:00Z",
  },
];

const streamers: Streamer[] = [
  {
    id: 7,
    name: "Streamer A",
  },
];

const createdEntry: DomainEntry = {
  entryId: 10,
  typeId: 2,
  typeKey: "person-name",
  typeLabel: "사람 이름",
  canonicalName: "테스트 인물",
  displayName: null,
  disambiguation: null,
  detail: "테스트 인물 설명",
  promptPolicy: "AUTO_ON_MATCH",
  priority: 50,
  isActive: true,
  sourceNote: null,
  streamers: [],
  aliases: [],
  createdAt: "2026-06-23T00:00:00Z",
  updatedAt: "2026-06-23T00:00:00Z",
};

describe("DomainKnowledgePage", () => {
  beforeEach(() => {
    routerPush.mockReset();
    for (const mock of Object.values(mutationMocks)) {
      mock.mockReset();
      mock.mockResolvedValue(createdEntry);
    }
    queryMocks.types.data = types;
    queryMocks.streamers.data = streamers;
    queryMocks.entries.data = { items: [] };
    queryMocks.entries.isLoading = false;
    queryMocks.entries.error = null;
    queryMocks.filters = undefined;
  });

  it("creates an entry with a new type label, streamer, and alias", async () => {
    render(<DomainKnowledgePage initialFilters={{ active: true, limit: 200 }} />);

    fireEvent.change(screen.getByLabelText("Canonical name"), {
      target: { value: "테스트 인물" },
    });
    fireEvent.change(screen.getAllByLabelText("Type")[1], {
      target: { value: "사람 이름" },
    });
    fireEvent.change(screen.getByLabelText("Detail"), {
      target: { value: "테스트 인물 설명" },
    });
    fireEvent.click(screen.getByLabelText("Streamer A"));
    fireEvent.change(screen.getByPlaceholderText("Surface form"), {
      target: { value: "테인" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(mutationMocks.createEntry).toHaveBeenCalledTimes(1));
    expect(mutationMocks.createEntry).toHaveBeenCalledWith({
      typeLabel: "사람 이름",
      canonicalName: "테스트 인물",
      displayName: undefined,
      disambiguation: undefined,
      detail: "테스트 인물 설명",
      promptPolicy: "AUTO_ON_MATCH",
      priority: 50,
      isActive: true,
      sourceNote: undefined,
      streamerIds: [7],
      aliases: [
        {
          surfaceForm: "테인",
          aliasKind: "ALIAS",
          certainty: "MEDIUM",
          applyScope: "SEARCH_ONLY",
          languageCode: null,
          note: null,
        },
      ],
    });
    expect(queryMocks.filters).toEqual({ active: true, limit: 200 });
  });
});
