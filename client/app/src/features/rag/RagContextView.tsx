import type { AnalysisSession } from "../../api/types";

export function RagContextView({ session }: { session: AnalysisSession }) {
  const status = session.results.pageindex_status ?? {};

  return (
    <div className="a4k-scrollbar h-full overflow-y-auto p-6">
      <h2 className="text-xl font-bold text-slate-100">RAG Context</h2>
      <p className="mt-1 text-sm text-slate-500">
        Retrieved content is auxiliary context only; crash facts and source inspection stay authoritative.
      </p>

      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <section className="rounded-md border border-blue-500/20 bg-blue-500/5 p-5">
          <h3 className="text-sm font-semibold text-blue-200">Similar Cases</h3>
          <div className="mt-4 rounded border border-slate-800 bg-slate-950/60 p-3 text-sm text-slate-400">
            No structured similar-case payload has been emitted yet. The backend can map persisted RAG
            cases here once it exposes the retrieval artifacts.
          </div>
        </section>

        <section className="rounded-md border border-slate-800 bg-slate-900/50 p-5">
          <h3 className="text-sm font-semibold text-slate-200">Linux Background</h3>
          <div className="mt-4 rounded border border-slate-800 bg-slate-950/60 p-3 text-sm text-slate-400">
            Background knowledge should stay separated from current-case evidence.
          </div>
        </section>
      </div>

      <section className="mt-5 rounded-md border border-slate-800 bg-slate-900/60 p-5">
        <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">
          PageIndex Status
        </h3>
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          {Object.entries(status).map(([key, value]) => (
            <div key={key} className="rounded border border-slate-800 bg-slate-950/50 p-3">
              <dt className="text-xs uppercase text-slate-600">{key}</dt>
              <dd className="mt-1 font-mono text-slate-300">{String(value)}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

