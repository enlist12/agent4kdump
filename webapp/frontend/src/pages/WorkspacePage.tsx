import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { createRun, getRun, listCases, listExperiences, listRuns, stopRun, subscribeToRun } from "../api";
import type { CaseRecord, ExperienceRecord, RunDetail, RunEvent, RunMode, RunStage, RunSummary } from "../types";

const STAGES: Array<{ key: RunStage; label: string }> = [
  { key: "config", label: "配置" },
  { key: "kdump_init", label: "初始化" },
  { key: "search", label: "检索" },
  { key: "rag", label: "RAG" },
  { key: "analyze", label: "分析" },
  { key: "persist", label: "沉淀" },
];

function stageState(run: RunDetail | null, stage: RunStage) {
  if (!run) return "idle";
  if (run.current_stage === stage && run.status === "running") return "active";
  const failed = run.events.some((event) => event.stage === stage && event.type === "stage_failed");
  const finished = run.events.some((event) => event.stage === stage && event.type === "stage_finished");
  if (failed) return "failed";
  if (finished) return "done";
  return "idle";
}

function Panel(props: { title: string; aside?: string; children: ReactNode; compact?: boolean }) {
  return (
    <section className={props.compact ? "panel compact" : "panel"}>
      <div className="panel-header">
        <p className="panel-title">{props.title}</p>
        {props.aside ? <span className="panel-aside">{props.aside}</span> : null}
      </div>
      {props.children}
    </section>
  );
}

export function WorkspacePage() {
  const [mode, setMode] = useState<RunMode>("live");
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [experiences, setExperiences] = useState<ExperienceRecord[]>([]);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [activeRun, setActiveRun] = useState<RunDetail | null>(null);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [selectedExperienceId, setSelectedExperienceId] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void Promise.all([listCases(), listExperiences(), listRuns()]).then(([caseRows, expRows, runRows]) => {
      setCases(caseRows);
      setExperiences(expRows);
      setRuns(runRows);
      if (caseRows[0]) setSelectedCaseId(caseRows[0].case_id);
      if (expRows[0]) setSelectedExperienceId(expRows[0].case_id);
    });
  }, []);

  useEffect(() => {
    if (!activeRun) return;
    const lastEvent = activeRun.events[activeRun.events.length - 1];
    const afterId = lastEvent?.id ?? 0;
    const source = subscribeToRun(activeRun.id, afterId, (event: RunEvent) => {
      setActiveRun((current) => {
        if (!current || current.id !== activeRun.id) return current;
        const deduped = new Map<number, RunEvent>();
        [...current.events, event].forEach((item) => deduped.set(item.id, item));
        const events = Array.from(deduped.values()).sort((a, b) => a.id - b.id);
        const artifacts = { ...current.artifacts };

        if (event.type === "config_ready") {
          artifacts.config_summary = (event.payload as any).config;
        }
        if (event.type === "search_result") artifacts.search_result = event.payload;
        if (event.type === "rag_context_ready") artifacts.rag_payload = event.payload;
        if (event.type === "analysis_result") artifacts.analysis_result = event.payload;
        if (event.type === "taint_trace_ready") artifacts.analysis_trace = event.payload;
        if (event.type === "experience_persisted") artifacts.persisted_case = event.payload;

        const next = { ...current, events, artifacts };
        if (event.type === "run_failed") {
          next.status = "failed";
          next.error = String(event.payload.summary ?? event.payload.error ?? "unknown error");
        }
        if (event.type === "run_canceled") {
          next.status = "canceled";
          next.error = String(event.payload.summary ?? "Stopped by user.");
        }
        if (event.type === "run_completed") {
          next.status = "completed";
          next.current_stage = "completed";
        }
        if (event.type === "stage_started" && event.stage) next.current_stage = event.stage;
        if (event.type === "stage_failed" && event.stage) next.current_stage = event.stage;

        setRuns((runItems) =>
          runItems.map((item) =>
            item.id === next.id
              ? {
                  ...item,
                  status: next.status,
                  current_stage: next.current_stage,
                  error: next.error,
                  updated_at: new Date().toISOString(),
                }
              : item,
          ),
        );

        return next;
      });
    });
    source.onerror = () => source.close();
    return () => source.close();
  }, [activeRun?.id]);

  const logs = useMemo(() => activeRun?.events.filter((event) => event.type === "log") ?? [], [activeRun]);
  const stageFailures = useMemo(
    () => activeRun?.events.filter((event) => event.type === "stage_failed") ?? [],
    [activeRun],
  );

  async function startRun() {
    setBusy(true);
    setError("");
    try {
      const created = await createRun({
        mode,
        case_id: mode === "live" ? selectedCaseId || undefined : undefined,
        experience_id: mode === "replay" ? selectedExperienceId || undefined : undefined,
        label: label || undefined,
      });
      const detail = await getRun(created.id);
      setActiveRun(detail);
      setRuns((current) => [created, ...current.filter((item) => item.id !== created.id)]);
    } catch (runError) {
      setError(runError instanceof Error ? runError.message : String(runError));
    } finally {
      setBusy(false);
    }
  }

  async function handleStopRun() {
    if (!activeRun) return;
    try {
      const updated = await stopRun(activeRun.id);
      setRuns((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setActiveRun((current) =>
        current
          ? {
              ...current,
              status: updated.status,
              error: "Stop requested. The current stage will terminate as soon as possible.",
            }
          : current,
      );
    } catch (stopError) {
      setError(stopError instanceof Error ? stopError.message : String(stopError));
    }
  }

  return (
    <div className="workspace-shell">
      <div className="workspace-toolbar">
        <div className="toolbar-left">
          <div className="segmented">
            <button className={mode === "live" ? "segment active" : "segment"} onClick={() => setMode("live")}>
              实时运行
            </button>
            <button className={mode === "replay" ? "segment active" : "segment"} onClick={() => setMode("replay")}>
              案例回放
            </button>
          </div>

          {mode === "live" ? (
            <select value={selectedCaseId} onChange={(event) => setSelectedCaseId(event.target.value)}>
              {cases.map((record) => (
                <option key={record.case_id} value={record.case_id}>
                  {record.case_id}
                </option>
              ))}
            </select>
          ) : (
            <select value={selectedExperienceId} onChange={(event) => setSelectedExperienceId(event.target.value)}>
              {experiences.map((record) => (
                <option key={record.case_id} value={record.case_id}>
                  {record.case_id}
                </option>
              ))}
            </select>
          )}

          <input value={label} onChange={(event) => setLabel(event.target.value)} placeholder="任务名，可选" />
          <button className="primary-button" disabled={busy} onClick={() => void startRun()}>
            {busy ? "提交中..." : mode === "live" ? "开始" : "回放"}
          </button>
          <button
            className="secondary-button"
            disabled={!activeRun || activeRun.status !== "running"}
            onClick={() => void handleStopRun()}
          >
            停止
          </button>
        </div>

        <div className="toolbar-right">
          {runs.slice(0, 6).map((run) => (
            <button
              key={run.id}
              className={activeRun?.id === run.id ? "run-pill active" : "run-pill"}
              onClick={() => void getRun(run.id).then(setActiveRun)}
            >
              <strong>{run.label}</strong>
              <span title={run.label}>{run.status}</span>
            </button>
          ))}
        </div>
      </div>

      {error ? <div className="status-banner error">{error}</div> : null}
      {activeRun?.error ? <div className="status-banner error">{activeRun.error}</div> : null}
      {!activeRun && !error ? <div className="status-banner">选择任务后开始查看日志和结果。</div> : null}

      <div className="workspace-main">
        <Panel title="运行日志" aside={activeRun ? `${logs.length} lines` : "idle"}>
          <div className="stage-strip">
            {STAGES.map((stage) => (
              <div key={stage.key} className={`stage-dot ${stageState(activeRun, stage.key)}`}>
                {stage.label}
              </div>
            ))}
          </div>

          <div className="log-panel core">
            {logs.length === 0 ? (
              <div className="empty-state">日志将显示模型输出、PageIndex 信息、Search Agent 质量检查和进程结束原因。</div>
            ) : (
              logs.map((event) => (
                <div key={event.id} className={`log-line ${String(event.payload.level ?? "info").toLowerCase()}`}>
                  <div className="log-meta">
                    <span>{new Date(event.timestamp).toLocaleTimeString()}</span>
                    <span className={`level-badge ${String(event.payload.level ?? "INFO").toLowerCase()}`}>
                      {String(event.payload.level ?? "INFO")}
                    </span>
                    <code>{String(event.payload.logger ?? "runtime")}</code>
                    {event.stage ? <strong>{event.stage}</strong> : null}
                  </div>
                  <p>{String(event.payload.message ?? "")}</p>
                </div>
              ))
            )}
          </div>
        </Panel>

        <div className="workspace-side">
          <Panel title="状态" aside={activeRun?.status || "idle"} compact>
            <div className="mini-stats">
              <div className="mini-stat">
                <span>任务</span>
                <strong>{activeRun?.label || "-"}</strong>
              </div>
              <div className="mini-stat">
                <span>阶段</span>
                <strong>{activeRun?.current_stage || "-"}</strong>
              </div>
              <div className="mini-stat">
                <span>模式</span>
                <strong>{activeRun?.mode || mode}</strong>
              </div>
            </div>
          </Panel>

          <Panel title="输入" compact>
            <ArtifactSummary data={activeRun?.artifacts.input_selection} />
          </Panel>

          <Panel title="配置摘要" compact>
            <ArtifactSummary data={activeRun?.artifacts.config_summary} />
          </Panel>

          {stageFailures.length ? (
            <Panel title="失败说明" compact>
              <div className="issue-list">
                {stageFailures.map((event) => (
                  <div key={event.id} className="issue-card">
                    <strong>{String(event.payload.title ?? event.stage ?? "stage failed")}</strong>
                    <p>{String(event.payload.error ?? "")}</p>
                  </div>
                ))}
              </div>
            </Panel>
          ) : null}
        </div>
      </div>

      <div className="workspace-results">
        <Panel title="检索结果" compact>
          <SearchArtifact data={activeRun?.artifacts.search_result} />
        </Panel>
        <Panel title="RAG" compact>
          <RagArtifact data={activeRun?.artifacts.rag_payload} />
        </Panel>
        <Panel title="根因分析" compact>
          <AnalysisArtifact analysis={activeRun?.artifacts.analysis_result} trace={activeRun?.artifacts.analysis_trace} />
        </Panel>
      </div>
    </div>
  );
}

function ArtifactSummary(props: { data: any }) {
  if (!props.data) return <div className="empty-state">暂无</div>;
  return (
    <div className="summary-list">
      {Object.entries(props.data).map(([key, value]) => (
        <div key={key} className="summary-row">
          <span>{key}</span>
          <strong>{Array.isArray(value) ? value.join(", ") : String(value)}</strong>
        </div>
      ))}
    </div>
  );
}

function SearchArtifact(props: { data: any }) {
  if (!props.data) return <div className="empty-state">暂无</div>;
  const candidates = props.data.candidate_matches ?? [];
  return (
    <div className="result-stack">
      <div className="summary-row">
        <span>判定</span>
        <strong>{props.data.is_known_bug ? "Known bug" : "Unknown bug"}</strong>
      </div>
      {props.data.final_reasoning ? <p className="result-copy">{String(props.data.final_reasoning)}</p> : null}
      {props.data.extra_info ? <p className="result-copy muted">{String(props.data.extra_info)}</p> : null}
      {candidates.length ? (
        <div className="candidate-list compact">
          {candidates.slice(0, 4).map((item: any, index: number) => (
            <article key={`${item.url}-${index}`} className="candidate-card compact">
              <strong className="candidate-title">{item.title || item.url}</strong>
              <span className="candidate-verdict">{item.verdict}</span>
              <p className="candidate-reason">{item.reason}</p>
            </article>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function RagArtifact(props: { data: any }) {
  if (!props.data) return <div className="empty-state">暂无</div>;
  return (
    <div className="result-stack">
      <div className="summary-row">
        <span>query</span>
        <strong>{String(props.data.query ?? "-")}</strong>
      </div>
      <div className="summary-row">
        <span>experience_hits</span>
        <strong>{String((props.data.experience_hits ?? []).length)}</strong>
      </div>
      <pre className="compact-pre">{String(props.data.context ?? "")}</pre>
    </div>
  );
}

function AnalysisArtifact(props: { analysis: any; trace: any }) {
  if (!props.analysis && !props.trace) return <div className="empty-state">暂无</div>;
  const patchSketch = String(props.analysis?.patch_sketch ?? "").trim();
  return (
    <div className="result-stack">
      {props.analysis ? (
        <>
          <div className="summary-row">
            <span>root_cause</span>
            <strong>{String(props.analysis.root_cause ?? "-")}</strong>
          </div>
          <div className="summary-row">
            <span>fix</span>
            <strong>{String(props.analysis.fix_suggestion ?? "-")}</strong>
          </div>
          {(props.analysis.root_cause_chain ?? []).length ? (
            <div className="chain-list compact">
              {(props.analysis.root_cause_chain ?? []).slice(0, 5).map((item: any) => (
                <article key={`${item.step}-${item.file}-${item.line}`} className="chain-item compact">
                  <span>{item.step}</span>
                  <div>
                    <strong>{item.function}</strong>
                    <p>
                      {item.file}:{item.line}
                    </p>
                  </div>
                </article>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
      {patchSketch ? <PatchSketchBlock patch={patchSketch} /> : null}
      {props.trace ? <pre className="compact-pre">{JSON.stringify(props.trace, null, 2)}</pre> : null}
    </div>
  );
}

function PatchSketchBlock(props: { patch: string }) {
  const lines = props.patch.split("\n");
  return (
    <div className="patch-card">
      <div className="patch-card-header">
        <span className="patch-title">patch_sketch</span>
      </div>
      <div className="patch-diff">
        {lines.map((line, index) => {
          let className = "patch-line";
          if (line.startsWith("+") && !line.startsWith("+++")) className += " add";
          else if (line.startsWith("-") && !line.startsWith("---")) className += " remove";
          else if (line.startsWith("@@")) className += " hunk";
          else if (line.startsWith("diff ") || line.startsWith("index ") || line.startsWith("---") || line.startsWith("+++")) className += " meta";
          return (
            <div key={`${index}-${line}`} className={className}>
              <code>{line || " "}</code>
            </div>
          );
        })}
      </div>
    </div>
  );
}
