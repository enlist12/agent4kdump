import { Terminal } from "lucide-react";
import type { AnalysisEvent } from "../../api/types";

export function LogConsole({ events }: { events: AnalysisEvent[] }) {
  return (
    <section className="flex min-h-0 flex-1 flex-col border-t border-border">
      <div className="flex items-center justify-between border-b border-border bg-slate-900/60 px-3 py-2">
        <span className="flex items-center gap-2 text-xs font-bold uppercase text-slate-400">
          <Terminal size={14} /> Live Logs
        </span>
        <span className="text-[10px] text-slate-600">Auto-scroll ON</span>
      </div>
      <div className="a4k-scrollbar min-h-0 flex-1 space-y-1 overflow-y-auto p-3 font-mono text-[11px]">
        {events.length === 0 ? (
          <p className="text-slate-600">[waiting] no runtime events yet</p>
        ) : (
          events.map((event) => (
            <p key={event.id} className={event.type === "error" ? "text-red-300" : "text-slate-400"}>
              <span className="text-slate-600">[{new Date(event.timestamp).toLocaleTimeString()}]</span>{" "}
              <span className="text-blue-300">{event.type}</span>{" "}
              {event.stage ? <span className="text-slate-500">({event.stage})</span> : null}
            </p>
          ))
        )}
      </div>
    </section>
  );
}

