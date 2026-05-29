import { AlertTriangle, CheckCircle2, Circle, Clock } from "lucide-react";
import type { StageStatus } from "../../api/types";

const labels: Record<string, string> = {
  config: "Config Validation",
  debugger: "Debugger Init",
  known_bug_search: "Known Bug Search",
  taint_analysis: "Taint Analysis",
  root_cause: "Root Cause Eval",
  report: "Report Generation",
  rag: "RAG Index"
};

export function StageSidebar({ stages }: { stages: Record<string, StageStatus> }) {
  return (
    <aside className="flex w-64 shrink-0 flex-col border-r border-border bg-slate-950/60 p-4">
      <h3 className="mb-4 text-xs font-bold uppercase tracking-widest text-slate-500">
        Analysis Stages
      </h3>
      <div className="space-y-1">
        {Object.entries(stages).map(([key, status]) => (
          <StageItem key={key} status={status} title={labels[key] ?? key} />
        ))}
      </div>
    </aside>
  );
}

function StageItem({ status, title }: { status: StageStatus; title: string }) {
  const style = {
    done: "border-emerald-500/10 bg-emerald-500/5 text-emerald-400",
    active: "border-blue-500/30 bg-blue-500/10 text-blue-300 shadow-[0_0_18px_rgba(37,99,235,0.12)]",
    pending: "border-transparent bg-transparent text-slate-600",
    failed: "border-red-500/30 bg-red-500/10 text-red-300"
  }[status];

  const icon = {
    done: <CheckCircle2 size={16} />,
    active: <Clock size={16} />,
    pending: <Circle size={16} />,
    failed: <AlertTriangle size={16} />
  }[status];

  return (
    <div className={`flex items-center gap-3 rounded-md border px-3 py-2.5 text-sm ${style}`}>
      {icon}
      <span className={status === "active" ? "font-semibold" : ""}>{title}</span>
    </div>
  );
}

