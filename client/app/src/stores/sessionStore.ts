import { create } from "zustand";
import type { AnalysisEvent, StageStatus } from "../api/types";

const initialStages: Record<string, StageStatus> = {
  config: "done",
  debugger: "done",
  known_bug_search: "active",
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
      if (event.stage && event.type.endsWith(".started")) {
        stages[event.stage] = "active";
      }
      if (event.stage && event.type.endsWith(".completed")) {
        stages[event.stage] = "done";
      }
      if (event.type === "error" && event.stage) {
        stages[event.stage] = "failed";
      }
      return {
        events: [...state.events, event].slice(-500),
        stages
      };
    })
}));

