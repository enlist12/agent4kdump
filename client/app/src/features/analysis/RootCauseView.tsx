import { FileCode2, Wrench } from "lucide-react";
import type { AnalysisSession } from "../../api/types";

export function RootCauseView({ session }: { session: AnalysisSession }) {
  const search = session.results.parsed_search;
  const analyze = session.results.parsed_analyze;

  return (
    <div className="a4k-scrollbar h-full overflow-y-auto p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-slate-100">Root Cause Analysis</h2>
          <p className="mt-1 text-sm text-slate-500">
            Search decision, trigger path and actionable fix direction.
          </p>
        </div>
        <span className="rounded border border-amber-500/20 bg-amber-500/10 px-3 py-1 text-xs text-amber-300">
          Known Bug: {search?.is_known_bug ? "true" : "false"}
        </span>
      </div>

      <div className="space-y-5">
        <section className="rounded-md border border-slate-800 bg-slate-900/60 p-5">
          <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">
            Primary Conclusion
          </h3>
          <p className="text-sm leading-7 text-slate-200">
            {analyze?.root_cause ?? "Root cause result is not available yet."}
          </p>
        </section>

        <section className="rounded-md border border-slate-800 bg-slate-900/60 p-5">
          <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">
            Trigger Path
          </h3>
          <p className="font-mono text-sm leading-7 text-blue-200">
            {analyze?.trigger_path ?? "No trigger path reported."}
          </p>
        </section>

        <section className="grid gap-5 lg:grid-cols-2">
          <div className="rounded-md border border-slate-800 bg-slate-900/60 p-5">
            <h3 className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-slate-500">
              <Wrench size={14} /> Fix Suggestion
            </h3>
            <p className="text-sm leading-7 text-slate-300">
              {analyze?.fix_suggestion ?? "No fix suggestion reported."}
            </p>
          </div>
          <div className="rounded-md border border-slate-800 bg-slate-900/60 p-5">
            <h3 className="mb-3 flex items-center gap-2 text-xs font-bold uppercase tracking-widest text-slate-500">
              <FileCode2 size={14} /> Patch Sketch
            </h3>
            <pre className="overflow-x-auto rounded bg-black/40 p-3 font-mono text-xs leading-6 text-emerald-200">
              {analyze?.patch_sketch ?? "// Patch sketch is not available yet."}
            </pre>
          </div>
        </section>

        <section className="rounded-md border border-slate-800 bg-slate-900/60 p-5">
          <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">
            Known Bug Search Evidence
          </h3>
          <p className="text-sm leading-7 text-slate-300">
            {search?.evidence ?? "Search evidence is not available yet."}
          </p>
        </section>
      </div>
    </div>
  );
}

