export type RunMode = "live" | "replay";
export type RunStatus = "queued" | "running" | "completed" | "failed" | "canceled";
export type RunStage =
  | "config"
  | "kdump_init"
  | "search"
  | "rag"
  | "analyze"
  | "persist"
  | "completed";

export interface RunSummary {
  id: string;
  mode: RunMode;
  label: string;
  status: RunStatus;
  current_stage?: RunStage | null;
  created_at: string;
  updated_at: string;
  case_id?: string | null;
  experience_id?: string | null;
  error?: string | null;
}

export interface RunEvent {
  id: number;
  run_id: string;
  timestamp: string;
  stage?: RunStage | null;
  type: string;
  payload: Record<string, unknown>;
}

export interface RunDetail extends RunSummary {
  events: RunEvent[];
  artifacts: Record<string, any>;
}

export interface CaseRecord {
  case_id: string;
  path: string;
  vmcore_path?: string | null;
  poc_path?: string | null;
  poc_source_path?: string | null;
  config_path?: string | null;
  has_vmcore: boolean;
  has_poc: boolean;
  has_config: boolean;
  file_count: number;
  updated_at?: string | null;
  poc_preview?: string | null;
  config_preview?: string | null;
}

export interface ExperienceRecord {
  case_id: string;
  created_at?: string | null;
  summary: string;
  root_cause: string;
  trigger_path: string;
  confidence: string;
  keywords: string[];
  kernel_version?: string | null;
  bug_type?: string | null;
  driver_candidates: string[];
  markdown_path?: string | null;
}

export interface ExperienceDetail extends ExperienceRecord {
  lessons: Record<string, any>;
  trace_summary: Record<string, any>;
  analysis_result: Record<string, any>;
  retrieved_context: Record<string, any>;
  retrieval_text: string;
  markdown_content: string;
}

export interface ProjectOverview {
  root_path: string;
  config_path: string;
  total_cases: number;
  total_experiences: number;
  syzbot_bug_files: number;
  rag_status: Record<string, any>;
  workflow: Array<{ name: string; description: string }>;
  modules: Array<{
    name: string;
    description: string;
    path: string;
    children?: Array<{ name: string; description: string; path: string }>;
  }>;
}

export interface ProjectTreeNode {
  name: string;
  path: string;
  type: string;
  children?: ProjectTreeNode[];
}
