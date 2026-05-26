import { useEffect } from "react";
import { subscribeSessionEvents } from "../api/client";
import type { AnalysisSession } from "../api/types";
import { EvidenceSidebar } from "../features/analysis/EvidenceSidebar";
import { LogConsole } from "../features/analysis/LogConsole";
import { RootCauseView } from "../features/analysis/RootCauseView";
import { StageSidebar } from "../features/analysis/StageSidebar";
import { RagContextView } from "../features/rag/RagContextView";
import { SourceViewer } from "../features/source/SourceViewer";
import { TaintFlowGraph } from "../features/taint-tree/TaintFlowGraph";
import { useSessionStore } from "../stores/sessionStore";

const tabs = [
  { id: "overview", label: "Root Cause" },
  { id: "taint", label: "Taint Tree" },
  { id: "rag", label: "RAG Context" },
  { id: "source", label: "Source Code" }
] as const;

export function SessionDetailView({ session }: { session: AnalysisSession }) {
  const activeView = useSessionStore((state) => state.activeView);
  const setActiveView = useSessionStore((state) => state.setActiveView);
  const addEvent = useSessionStore((state) => state.addEvent);
  const events = useSessionStore((state) => state.events);
  const stages = useSessionStore((state) => state.stages);

  useEffect(() => subscribeSessionEvents(session.id, addEvent), [addEvent, session.id]);

  return (
    <div className="flex h-full overflow-hidden bg-slate-950">
      <StageSidebar stages={stages} />

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <section className="flex min-w-0 flex-1 flex-col">
            <div className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-slate-900/70 px-4">
              <div className="flex gap-1">
                {tabs.map((tab) => (
                  <button
                    key={tab.id}
                    onClick={() => setActiveView(tab.id)}
                    className={`rounded px-3 py-1.5 text-sm transition ${
                      activeView === tab.id
                        ? "bg-blue-600 text-white"
                        : "text-slate-400 hover:bg-slate-800 hover:text-slate-100"
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              <span className="text-xs text-slate-500">{session.id}</span>
            </div>

            <div className="min-h-0 flex-1 overflow-hidden">
              {activeView === "overview" ? <RootCauseView session={session} /> : null}
              {activeView === "taint" ? <TaintFlowGraph /> : null}
              {activeView === "rag" ? <RagContextView session={session} /> : null}
              {activeView === "source" ? <SourceViewer session={session} /> : null}
            </div>
          </section>

          <EvidenceSidebar session={session} />
        </div>

        <div className="h-56 shrink-0">
          <LogConsole events={events} />
        </div>
      </div>
    </div>
  );
}

