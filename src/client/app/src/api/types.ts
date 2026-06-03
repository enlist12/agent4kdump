export type SessionStatus =
  | "created"
  | "validating"
  | "ready"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type StageStatus = "pending" | "active" | "done" | "failed";

export interface AnalysisConfigPayload {
  config_path?: string | null;
  linux_path?: string | null;
  gdb_path?: string | null;
  vmcore?: string | null;
  kdump_server?: string | null;
  enable_rag: boolean;
  build_codequery: boolean;
  rag_cache_dir?: string | null;
  kdump_host: string;
  kdump_port: number;
  kdump_args?: string[] | null;
  recursion_limit?: number;
}

export interface CrashFingerprint {
  fault_type: string;
  crash_function: string;
  top_frames: string[];
  source_path?: string | null;
  title_candidates: string[];
}

export interface SearchQueryRecord {
  query: string;
  target_domains: string[];
  observed_result: string;
}

export interface KnownBugAnalysisResult {
  is_known_bug: boolean;
  evidence: string;
  matched_url?: string[] | null;
  extra_info?: string | null;
  verification_details?: string | null;
  crash_fingerprint?: CrashFingerprint | null;
  queries_tried: SearchQueryRecord[];
}

export interface RootCauseAnalysisResult {
  root_cause: string;
  trigger_path: string;
  evidence: string[];
  fix_suggestion: string;
  confidence?: string | number;
  patch_sketch?: string;
  uncertainty?: string;
  crash_site?: {
    file?: string;
    function?: string;
    line?: number;
    statement?: string;
    invalid_object?: string;
  };
  key_locations?: Array<{
    role: "cause" | "propagation" | "fix";
    file: string;
    function: string;
    line: number;
    object: string;
    detail: string;
  }>;
  verification_todo?: string[];
}

export interface SessionResultPayload {
  parsed_search?: KnownBugAnalysisResult | null;
  parsed_analyze?: RootCauseAnalysisResult | null;
  pageindex_status?: Record<string, unknown> | null;
  rag_context?: RagContextPayload | null;
  taint_nodes?: TaintNodePayload[];
  source_snippets?: SourceSnippetPayload[];
  report_markdown?: string | null;
}

export interface AnalysisSession {
  id: string;
  name: string;
  status: SessionStatus;
  config: AnalysisConfigPayload;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  results: SessionResultPayload;
}

export interface AnalysisEvent {
  id: string;
  session_id: string;
  type: string;
  stage?: string | null;
  timestamp: string;
  payload: Record<string, unknown>;
}

export interface UploadVmcoreResponse {
  filename: string;
  stored_path: string;
  size: number;
}

export interface EnvVarStatus {
  configured: boolean;
  masked: string;
  value?: string;
  sensitive?: boolean;
}

export interface EnvSettingsResponse {
  path: string;
  values: Record<string, EnvVarStatus>;
}

export interface ImportEnvFilePayload {
  filename?: string | null;
  content: string;
}

export interface TaintNodePayload {
  id: string;
  parent_id?: string | null;
  status: "pending" | "running" | "done" | "failed" | "pruned";
  file_name: string;
  line: number;
  variable_name: string;
  current_function: string;
  explain: string;
  end: boolean;
  branch?: string | null;
  error?: string | null;
}

export interface RagContextPayload {
  context?: string | null;
  similar_cases?: Array<Record<string, unknown>>;
  experience_hits?: Array<Record<string, unknown>>;
  linux_background?: unknown;
  [key: string]: unknown;
}

export interface SourceSnippetPayload {
  file_name: string;
  line: number;
  function?: string | null;
  label?: string | null;
  content: string;
}
