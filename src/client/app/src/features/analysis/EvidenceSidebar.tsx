import { ExternalLink, ShieldAlert } from "lucide-react";
import type { ReactNode } from "react";
import type { AnalysisSession } from "../../api/types";
import { platform } from "../../platform/adapter";

export function EvidenceSidebar({ session }: { session: AnalysisSession }) {
  const search = session.results.parsed_search;
  const analyze = session.results.parsed_analyze;

  return (
    <aside className="flex w-80 shrink-0 flex-col border-l border-border bg-slate-950/80">
      <div className="border-b border-border px-4 py-3">
        <h3 className="text-xs font-bold uppercase tracking-widest text-slate-500">
          Evidence Context
        </h3>
      </div>
      <div className="a4k-scrollbar min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
        <Panel title="Crash Fingerprint">
          <dl className="space-y-2 text-xs">
            <Row label="Fault" value={search?.crash_fingerprint?.fault_type ?? "unknown"} />
            <Row label="Function" value={search?.crash_fingerprint?.crash_function ?? "unknown"} />
            <Row label="Source" value={search?.crash_fingerprint?.source_path ?? "unknown"} />
          </dl>
        </Panel>

        <Panel title="Matched URLs">
          {search?.matched_url?.length ? (
            <div className="space-y-2">
              {search.matched_url.map((url) => (
                <button
                  key={url}
                  onClick={() => void platform.openUrl(url)}
                  className="flex w-full items-center gap-2 rounded border border-slate-700 bg-slate-900 px-2 py-2 text-left text-xs text-blue-300 hover:bg-slate-800"
                >
                  <ExternalLink size={13} /> <span className="truncate">{url}</span>
                </button>
              ))}
            </div>
          ) : (
            <p className="text-xs text-slate-500">No exact known-bug URL matched.</p>
          )}
        </Panel>

        <Panel title="Analysis Evidence">
          <ul className="space-y-2 text-xs text-slate-400">
            {(analyze?.evidence ?? []).map((item) => (
              <li key={item} className="rounded border border-slate-800 bg-slate-900/70 p-2">
                {item}
              </li>
            ))}
          </ul>
        </Panel>

        <Panel title="Uncertainty">
          <p className="flex gap-2 text-xs leading-relaxed text-amber-300">
            <ShieldAlert size={15} className="mt-0.5 shrink-0" />
            {analyze?.uncertainty ?? "No uncertainty note reported yet."}
          </p>
        </Panel>
      </div>
    </aside>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-md border border-slate-800 bg-slate-900/40">
      <div className="border-b border-slate-800 px-3 py-2 text-[11px] font-bold uppercase text-slate-500">
        {title}
      </div>
      <div className="p-3">{children}</div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-slate-600">{label}</dt>
      <dd className="mt-0.5 truncate font-mono text-slate-300">{value}</dd>
    </div>
  );
}
