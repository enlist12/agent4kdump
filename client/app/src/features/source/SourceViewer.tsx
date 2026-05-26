import type { AnalysisSession } from "../../api/types";

export function SourceViewer({ session }: { session: AnalysisSession }) {
  const patch = session.results.parsed_analyze?.patch_sketch;
  const crashSite = session.results.parsed_analyze?.crash_site;

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
          <div className="text-xs uppercase text-slate-600">Crash Site</div>
          <div className="mt-1 font-mono text-blue-200">
            {crashSite?.file ?? "fs/ext4/inode.c"}:{crashSite?.line ?? "unknown"}
          </div>
        </div>
        <pre className="min-h-[420px] overflow-auto rounded-md border border-slate-800 bg-black/50 p-4 font-mono text-xs leading-6 text-slate-300">
          {patch ?? "/* Source viewer placeholder. Wire /api/sessions/{id}/source next. */"}
        </pre>
      </div>
    </div>
  );
}

