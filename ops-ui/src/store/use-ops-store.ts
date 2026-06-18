import { create } from "zustand";
import { persist } from "zustand/middleware";

type SchemaNodePosition = {
  x: number;
  y: number;
};

type OpsState = {
  videoSearch: string;
  videoTaskStatus: string;
  selectedSchemaTableId: string | null;
  schemaNodePositions: Record<string, SchemaNodePosition>;
  setVideoSearch: (value: string) => void;
  setVideoTaskStatus: (value: string) => void;
  setSelectedSchemaTableId: (value: string | null) => void;
  setSchemaNodePosition: (tableId: string, position: SchemaNodePosition) => void;
  setSchemaNodePositions: (positions: Record<string, SchemaNodePosition>) => void;
  resetSchemaNodePositions: () => void;
};

export const useOpsStore = create<OpsState>()(
  persist(
    (set) => ({
      videoSearch: "",
      videoTaskStatus: "",
      selectedSchemaTableId: null,
      schemaNodePositions: {},
      setVideoSearch: (videoSearch) => set({ videoSearch }),
      setVideoTaskStatus: (videoTaskStatus) => set({ videoTaskStatus }),
      setSelectedSchemaTableId: (selectedSchemaTableId) => set({ selectedSchemaTableId }),
      setSchemaNodePosition: (tableId, position) =>
        set((state) => ({
          schemaNodePositions: {
            ...state.schemaNodePositions,
            [tableId]: position,
          },
        })),
      setSchemaNodePositions: (schemaNodePositions) => set({ schemaNodePositions }),
      resetSchemaNodePositions: () => set({ schemaNodePositions: {} }),
    }),
    {
      name: "codex-ops-ui",
      partialize: (state) => ({
        videoSearch: state.videoSearch,
        videoTaskStatus: state.videoTaskStatus,
        selectedSchemaTableId: state.selectedSchemaTableId,
        schemaNodePositions: state.schemaNodePositions,
      }),
    },
  ),
);
