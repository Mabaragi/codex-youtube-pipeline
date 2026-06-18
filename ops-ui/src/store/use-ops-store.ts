import { create } from "zustand";

type OpsState = {
  videoSearch: string;
  videoTaskStatus: string;
  selectedSchemaTableId: string | null;
  setVideoSearch: (value: string) => void;
  setVideoTaskStatus: (value: string) => void;
  setSelectedSchemaTableId: (value: string | null) => void;
};

export const useOpsStore = create<OpsState>((set) => ({
  videoSearch: "",
  videoTaskStatus: "",
  selectedSchemaTableId: null,
  setVideoSearch: (videoSearch) => set({ videoSearch }),
  setVideoTaskStatus: (videoTaskStatus) => set({ videoTaskStatus }),
  setSelectedSchemaTableId: (selectedSchemaTableId) => set({ selectedSchemaTableId }),
}));
