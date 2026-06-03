import type { AnalysisSession } from "../../api/types";

export function SourceViewer({ session }: { session: AnalysisSession }) {
  const snippets = session.results.source_snippets ?? [];
  const firstSnippet = snippets[0];

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border px-5 py-3">
        <h2 className="text-sm font-semibold text-slate-200">Source Code</h2>
        <p className="mt-1 text-xs text-slate-500">
          Monaco can replace this read-only panel when source API is wired.
        </p>
      </div>
      <div className="a4k-scrollbar min-h-0 flex-1 overflow-auto p-5">
        <div className="mb-4 rounded border border-slate-800 bg-slate-900/60 p-4 text-sm">
          <div className="text-xs uppercase text-slate-600">Focused Location</div>
          <div className="mt-1 font-mono text-blue-200">
            {firstSnippet ? `${firstSnippet.file_name}:${firstSnippet.line}` : "unknown"}
          </div>
        </div>
        {snippets.length ? (
          <div className="space-y-4">
            {snippets.map((snippet) => (
              <section key={`${snippet.file_name}:${snippet.line}`} className="rounded-md border border-slate-800 bg-black/40">
                <div className="border-b border-slate-800 px-4 py-2 font-mono text-xs text-slate-400">
                  {snippet.file_name}:{snippet.line}
                  {snippet.function ? <span className="text-slate-600"> | {snippet.function}</span> : null}
                  {snippet.label ? <span className="text-slate-600"> | {snippet.label}</span> : null}
                </div>
                <pre className="overflow-auto p-4 font-mono text-xs leading-6 text-slate-300">
                  {snippet.content}
                </pre>
              </section>
            ))}
          </div>
        ) : (
          <pre className="min-h-[420px] overflow-auto rounded-md border border-slate-800 bg-black/50 p-4 font-mono text-xs leading-6 text-slate-500">
            No source snippets have been emitted for this session yet.
          </pre>
        )}
      </div>
    </div>
  );
}
