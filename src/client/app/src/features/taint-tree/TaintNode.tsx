import { Handle, Position } from "reactflow";
import type { TaintNodePayload } from "../../api/types";

const statusStyle = {
  pending: "border-slate-700 bg-slate-900 text-slate-300",
  running: "border-blue-500 bg-blue-950/60 text-blue-100 shadow-lg shadow-blue-950/40",
  done: "border-emerald-500/60 bg-emerald-950/30 text-emerald-100",
  failed: "border-red-500/70 bg-red-950/40 text-red-100",
  pruned: "border-amber-500/60 bg-amber-950/30 text-amber-100"
};

export function TaintNode({ data }: { data: TaintNodePayload }) {
  return (
    <div className={`w-64 rounded-md border-2 px-4 py-3 shadow-xl ${statusStyle[data.status]}`}>
      <Handle type="target" position={Position.Top} className="h-2 w-2" />
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-[11px] font-mono text-slate-400">
            {data.file_name}:{data.line}
          </div>
          <div className="mt-1 truncate text-sm font-bold">{data.current_function}</div>
        </div>
        <span className="rounded bg-slate-950/70 px-2 py-0.5 text-[10px] uppercase text-slate-400">
          {data.status}
        </span>
      </div>
      <div className="mt-3 rounded bg-slate-950/70 px-2 py-1 font-mono text-xs text-blue-200">
        {data.variable_name}
      </div>
      {data.branch ? <div className="mt-2 text-[11px] text-amber-300">{data.branch}</div> : null}
      <Handle type="source" position={Position.Bottom} className="h-2 w-2" />
    </div>
  );
}

