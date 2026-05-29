import { useMemo } from "react";
import { Terminal } from "lucide-react";
import type { AnalysisEvent } from "../../api/types";

function formatEvent(event: AnalysisEvent): { time: string; text: string; isError: boolean } {
  const time = new Date(event.timestamp).toLocaleTimeString();
  const parts = [event.type];
  if (event.stage) {
    parts.push("(" + event.stage + ")");
  }
  if (event.payload) {
    const p = event.payload;
    if (event.type === "error" && p.message) {
      parts.push(String(p.message));
    } else if (p.message) {
      parts.push("— " + String(p.message));
    } else if (event.type === "config.validated" && p.config_path) {
      parts.push(
        "— vmcore=" + String(p.vmcore ?? "-") + " port=" + String(p.kdump_port ?? "-")
      );
    }
  }
  return { time, text: parts.join(" "), isError: event.type === "error" };
}

export function LogConsole({ events }: { events: AnalysisEvent[] }) {
  const lines = useMemo(
    () => events.map((event) => ({ id: event.id, ...formatEvent(event) })),
    [events]
  );

  return (
    <section className="flex min-h-0 flex-1 flex-col border-t border-border">
      <div className="flex items-center justify-between border-b border-border bg-slate-900/60 px-3 py-2">
        <span className="flex items-center gap-2 text-xs font-bold uppercase text-slate-400">
          <Terminal size={14} /> Live Logs
        </span>
        <span className="text-[10px] text-slate-600">Auto-scroll ON</span>
      </div>
      <div className="a4k-scrollbar min-h-0 flex-1 space-y-1 overflow-y-auto p-3 font-mono text-[11px]">
        {lines.length === 0 ? (
          <p className="text-slate-600">[waiting] no runtime events yet</p>
        ) : (
          lines.map((line) => (
            <p key={line.id} className={line.isError ? "text-red-300" : "text-slate-400"}>
              <span className="text-slate-600">[{line.time}]</span> {line.text}
            </p>
          ))
        )}
      </div>
    </section>
  );
}
