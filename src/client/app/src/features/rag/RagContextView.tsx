import type { AnalysisSession } from "../../api/types";

export function RagContextView({ session }: { session: AnalysisSession }) {
  const status = session.results.pageindex_status ?? {};
  const context = session.results.rag_context;
  const similarCases = context?.similar_cases ?? context?.experience_hits ?? [];
  const linuxBackground = context?.linux_background;
  const contextText = context?.context;

  return (
    <div className="a4k-scrollbar h-full overflow-y-auto p-6">
      <h2 className="text-xl font-bold text-slate-100">RAG Context</h2>
      <p className="mt-1 text-sm text-slate-500">
        Retrieved content is auxiliary context only; crash facts and source inspection stay authoritative.
      </p>

      <div className="mt-6 grid gap-5 lg:grid-cols-2">
        <section className="rounded-md border border-blue-500/20 bg-blue-500/5 p-5">
          <h3 className="text-sm font-semibold text-blue-200">Similar Cases</h3>
          <div className="mt-4 space-y-3 text-sm text-slate-300">
            {similarCases.length ? similarCases.map((item, index) => (
              <pre key={index} className="overflow-auto rounded border border-slate-800 bg-slate-950/60 p-3 text-xs leading-5 text-slate-300">
                {JSON.stringify(item, null, 2)}
              </pre>
            )) : (
              <div className="rounded border border-slate-800 bg-slate-950/60 p-3 text-slate-500">
                No similar cases were returned for this session.
              </div>
            )}
          </div>
        </section>

        <section className="rounded-md border border-slate-800 bg-slate-900/50 p-5">
          <h3 className="text-sm font-semibold text-slate-200">Linux Background</h3>
          <pre className="mt-4 max-h-72 overflow-auto rounded border border-slate-800 bg-slate-950/60 p-3 text-xs leading-5 text-slate-300">
            {linuxBackground ? (
              typeof linuxBackground === "string" ? linuxBackground : JSON.stringify(linuxBackground, null, 2)
            ) : "No Linux background payload was returned for this session."}
          </pre>
        </section>
      </div>

      <section className="mt-5 rounded-md border border-slate-800 bg-slate-900/60 p-5">
        <h3 className="mb-3 text-xs font-bold uppercase tracking-widest text-slate-500">
          Retrieved Context
        </h3>
        <pre className="max-h-96 overflow-auto whitespace-pre-wrap rounded border border-slate-800 bg-slate-950/60 p-3 text-xs leading-5 text-slate-300">
          {contextText || "No RAG context has been emitted for this session."}
        </pre>
      </section>

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
