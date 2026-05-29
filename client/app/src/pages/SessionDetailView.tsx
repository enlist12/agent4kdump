import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { cancelSession, runSession, subscribeSessionEvents } from "../api/client";
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
  const clearEvents = useSessionStore((state) => state.clearEvents);
  const queryClient = useQueryClient();
  const [actionLoading, setActionLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [sseKey, setSseKey] = useState(0);

  useEffect(() => {
    const unsubscribe = subscribeSessionEvents(session.id, (event) => {
      addEvent(event);
      if (
        event.type === "session.completed" ||
        event.type === "session.cancelled" ||
        event.type === "error"
      ) {
        void queryClient.invalidateQueries({ queryKey: ["session", session.id] });
        void queryClient.invalidateQueries({ queryKey: ["sessions"] });
      }
    });
    return () => {
      unsubscribe();
      void queryClient.invalidateQueries({ queryKey: ["session", session.id] });
    };
  }, [addEvent, session.id, queryClient, sseKey]);

  const handleStartAnalysis = useCallback(async () => {
    setActionLoading(true);
    setActionError(null);
    clearEvents();
    try {
      const updated = await runSession(session.id);
      queryClient.setQueryData(["session", session.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
      setSseKey((k) => k + 1);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(false);
    }
  }, [session.id, queryClient, clearEvents]);

  const handleStopAnalysis = useCallback(async () => {
    setActionLoading(true);
    setActionError(null);
    try {
      const updated = await cancelSession(session.id);
      queryClient.setQueryData(["session", session.id], updated);
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setActionLoading(false);
    }
  }, [session.id, queryClient]);

  const isRunning = session.status === "validating" || session.status === "running";
  const isTerminal = session.status === "completed" || session.status === "failed" || session.status === "cancelled";

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
              <div className="flex items-center gap-3">
                {session.status === "created" || session.status === "ready" ? (
                  <button
                    onClick={handleStartAnalysis}
                    disabled={actionLoading}
                    className="flex items-center gap-1.5 rounded bg-green-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-green-500 disabled:opacity-60"
                  >
                    {actionLoading ? (
                      <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    ) : (
                      <span className="text-base leading-none">&#9654;</span>
                    )}
                    Start Analysis
                  </button>
                ) : null}
                {isRunning ? (
                  <button
                    onClick={handleStopAnalysis}
                    disabled={actionLoading}
                    className="flex items-center gap-1.5 rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-red-500 disabled:opacity-60"
                  >
                    {actionLoading ? (
                      <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    ) : (
                      <span className="text-base leading-none">&#9632;</span>
                    )}
                    Stop
                  </button>
                ) : null}
                {isTerminal ? (
                  <button
                    onClick={handleStartAnalysis}
                    disabled={actionLoading}
                    className="flex items-center gap-1.5 rounded bg-amber-600 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-amber-500 disabled:opacity-60"
                  >
                    {actionLoading ? (
                      <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
                    ) : (
                      <span className="text-base leading-none">&#8635;</span>
                    )}
                    Restart
                  </button>
                ) : null}
                <span className="text-xs text-slate-500">{session.id}</span>
              </div>
            </div>

            {actionError ? (
              <div className="flex items-start gap-2 border-b border-red-500/30 bg-red-500/10 px-4 py-2.5">
                <span className="mt-0.5 shrink-0 text-red-400 text-sm font-bold">!</span>
                <div className="min-w-0 flex-1">
                  <span className="text-xs font-bold uppercase tracking-widest text-red-400">Request Failed</span>
                  <p className="mt-0.5 text-xs leading-5 text-red-300 break-all">{actionError}</p>
                </div>
                <button
                  onClick={() => setActionError(null)}
                  className="shrink-0 text-xs text-red-400 hover:text-red-200 transition"
                >
                  Dismiss
                </button>
              </div>
            ) : null}
            {session.error ? (
              <div className="flex items-start gap-2 border-b border-red-500/30 bg-red-500/10 px-4 py-2.5">
                <span className="mt-0.5 shrink-0 text-red-400 text-sm font-bold">!</span>
                <div className="min-w-0">
                  <span className="text-xs font-bold uppercase tracking-widest text-red-400">Analysis Failed</span>
                  <p className="mt-0.5 text-xs leading-5 text-red-300 break-all">{session.error}</p>
                </div>
              </div>
            ) : null}

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

