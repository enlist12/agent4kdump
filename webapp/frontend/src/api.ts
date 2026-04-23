import type {
  CaseRecord,
  ExperienceDetail,
  ExperienceRecord,
  ProjectOverview,
  ProjectTreeNode,
  RunDetail,
  RunEvent,
  RunMode,
  RunSummary,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      "Content-Type": "application/json",
    },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function listCases(): Promise<CaseRecord[]> {
  return request<CaseRecord[]>("/api/cases");
}

export function getCase(caseId: string): Promise<CaseRecord> {
  return request<CaseRecord>(`/api/cases/${caseId}`);
}

export function listExperiences(): Promise<ExperienceRecord[]> {
  return request<ExperienceRecord[]>("/api/experience");
}

export function getExperience(caseId: string): Promise<ExperienceDetail> {
  return request<ExperienceDetail>(`/api/experience/${caseId}`);
}

export function listRuns(): Promise<RunSummary[]> {
  return request<RunSummary[]>("/api/runs");
}

export function getRun(runId: string): Promise<RunDetail> {
  return request<RunDetail>(`/api/runs/${runId}`);
}

export function createRun(payload: {
  mode: RunMode;
  case_id?: string;
  experience_id?: string;
  label?: string;
  config_override?: Record<string, unknown>;
}): Promise<RunSummary> {
  return request<RunSummary>("/api/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function stopRun(runId: string): Promise<RunSummary> {
  return request<RunSummary>(`/api/runs/${runId}/stop`, {
    method: "POST",
  });
}

export function subscribeToRun(
  runId: string,
  afterId: number,
  onEvent: (event: RunEvent) => void,
): EventSource {
  const source = new EventSource(`${API_BASE}/api/runs/${runId}/events?after=${afterId}`);
  const eventTypes = [
    "run_created",
    "run_failed",
    "run_completed",
    "run_canceled",
    "run_stop_requested",
    "stage_started",
    "stage_finished",
    "stage_failed",
    "log",
    "config_ready",
    "search_result",
    "rag_context_ready",
    "taint_trace_ready",
    "analysis_result",
    "experience_persisted",
  ];
  eventTypes.forEach((eventType) => {
    source.addEventListener(eventType, (message) => {
      const parsed = JSON.parse((message as MessageEvent).data) as RunEvent;
      onEvent(parsed);
    });
  });
  return source;
}

export function getProjectOverview(): Promise<ProjectOverview> {
  return request<ProjectOverview>("/api/project/overview");
}

export function getProjectTree(): Promise<ProjectTreeNode[]> {
  return request<ProjectTreeNode[]>("/api/project/tree");
}
