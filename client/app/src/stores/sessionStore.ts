import { create } from "zustand";
import type { AnalysisEvent, StageStatus } from "../api/types";

const initialStages: Record<string, StageStatus> = {
  config: "pending",
  debugger: "pending",
  known_bug_search: "pending",
  taint_analysis: "pending",
  root_cause: "pending",
  report: "pending"
};

interface SessionUiState {
  activeSessionId: string | null;
  activeView: "overview" | "taint" | "rag" | "source";
  events: AnalysisEvent[];
  stages: Record<string, StageStatus>;
  setActiveSessionId: (sessionId: string) => void;
  setActiveView: (view: SessionUiState["activeView"]) => void;
  addEvent: (event: AnalysisEvent) => void;
  clearEvents: () => void;
}

export const useSessionStore = create<SessionUiState>((set) => ({
  activeSessionId: null,
  activeView: "overview",
  events: [],
  stages: initialStages,
  setActiveSessionId: (sessionId) => set({ activeSessionId: sessionId }),
  setActiveView: (activeView) => set({ activeView }),
  addEvent: (event) =>
    set((state) => {
      const stages = { ...state.stages };
      if (event.stage) {
        // Initialize stage on first mention
        if (!(event.stage in stages)) {
          stages[event.stage] = "active";
        }
        // stage begins
        if (
          event.type.endsWith(".validation_started") ||
          event.type.endsWith(".starting")
        ) {
          stages[event.stage] = "active";
        }
        // stage ends
        if (
          event.type.endsWith(".validated") ||
          event.type.endsWith(".started") ||
          event.type.endsWith(".completed")
        ) {
          stages[event.stage] = "done";
        }
      }
      if (event.type === "error" && event.stage) {
        stages[event.stage] = "failed";
      }
      return {
        events: [...state.events, event].slice(-500),
        stages
      };
    }),
  clearEvents: () => set({ events: [], stages: { ...initialStages } })
}));

