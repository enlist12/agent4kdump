import { Activity, FilePlus2, Loader2, PlayCircle, UploadCloud } from "lucide-react";
import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { createSession, uploadVmcore } from "../api/client";
import type { AnalysisConfigPayload, AnalysisSession } from "../api/types";

export function Dashboard({
  sessions,
  onOpenAnalysis,
  onSessionCreated
}: {
  sessions: AnalysisSession[];
  onOpenAnalysis: (sessionId: string) => void;
  onSessionCreated: (session: AnalysisSession) => void;
}) {
  const [showNewSession, setShowNewSession] = useState(false);

  return (
    <div className="a4k-scrollbar h-full overflow-y-auto bg-slate-950 p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-100">agent4kdump Workbench</h1>
          <p className="mt-1 text-sm text-slate-500">
            Web-first crash analysis client for kdump sessions.
          </p>
        </div>
        <button
          onClick={() => setShowNewSession((value) => !value)}
          className="flex items-center gap-2 rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500"
        >
          <FilePlus2 size={16} /> New Session
        </button>
      </div>

      {showNewSession ? (
        <NewSessionPanel
          onCancel={() => setShowNewSession(false)}
          onCreated={(session) => {
            setShowNewSession(false);
            onSessionCreated(session);
          }}
        />
      ) : null}

      <div className="grid gap-4 md:grid-cols-3">
        <Metric label="Sessions" value={String(sessions.length)} icon={<Activity size={18} />} />
        <Metric label="Running" value={String(sessions.filter((item) => item.status === "running").length)} icon={<PlayCircle size={18} />} />
        <Metric label="Completed" value={String(sessions.filter((item) => item.status === "completed").length)} icon={<Activity size={18} />} />
      </div>

      <section className="mt-6 rounded-md border border-border bg-slate-900/60">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-200">Recent Sessions</h2>
        </div>
        <div className="divide-y divide-slate-800">
          {sessions.map((session) => (
            <button
              key={session.id}
              onClick={() => onOpenAnalysis(session.id)}
              className="grid w-full grid-cols-[1fr_auto] gap-4 px-4 py-4 text-left transition hover:bg-slate-800/50"
            >
              <div>
                <div className="font-mono text-sm text-slate-100">{session.name}</div>
                <div className="mt-1 text-xs text-slate-500">{session.config.vmcore ?? "vmcore not set"}</div>
              </div>
              <span className="self-center rounded border border-blue-500/20 bg-blue-500/10 px-2 py-1 text-xs uppercase text-blue-300">
                {session.status}
              </span>
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}

function NewSessionPanel({
  onCreated,
  onCancel
}: {
  onCreated: (session: AnalysisSession) => void;
  onCancel: () => void;
}) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [name, setName] = useState("kernel_crash_analysis");
  const [linuxPath, setLinuxPath] = useState("");
  const [gdbPath, setGdbPath] = useState("auto");
  const [vmcorePath, setVmcorePath] = useState("");
  const [kdumpServer, setKdumpServer] = useState("auto");
  const [enableRag, setEnableRag] = useState(false);
  const [buildCodequery, setBuildCodequery] = useState(true);
  const [recursionLimit, setRecursionLimit] = useState(300);
  const [selectedVmcore, setSelectedVmcore] = useState<File | null>(null);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    setUploadProgress(0);

    try {
      let finalVmcorePath = vmcorePath.trim();
      if (selectedVmcore) {
        const upload = await uploadVmcore(selectedVmcore, setUploadProgress);
        finalVmcorePath = upload.stored_path;
      }

      const config: AnalysisConfigPayload = {
        linux_path: linuxPath.trim() || null,
        gdb_path: gdbPath.trim() || "auto",
        vmcore: finalVmcorePath || null,
        kdump_server: kdumpServer.trim() || "auto",
        enable_rag: enableRag,
        build_codequery: buildCodequery,
        rag_cache_dir: "./cache/rag",
        kdump_host: "127.0.0.1",
        kdump_port: 1234,
        recursion_limit: recursionLimit
      };
      const session = await createSession(name.trim() || "kernel_crash_analysis", config);
      onCreated(session);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to create session.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={submit} className="mb-6 rounded-md border border-blue-500/20 bg-slate-900/70 p-4">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-100">New kdump Session</h2>
          <p className="mt-1 text-xs text-slate-500">
            Upload a local vmcore or provide a server-side vmcore path.
          </p>
        </div>
        <button type="button" onClick={onCancel} className="text-xs text-slate-500 hover:text-slate-200">
          Cancel
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Field label="Session Name">
          <input value={name} onChange={(event) => setName(event.target.value)} className="a4k-input" />
        </Field>
        <Field label="Linux Source Path">
          <input value={linuxPath} onChange={(event) => setLinuxPath(event.target.value)} className="a4k-input" placeholder="/path/to/linux" />
        </Field>
        <Field label="GDB Path">
          <input value={gdbPath} onChange={(event) => setGdbPath(event.target.value)} className="a4k-input" />
        </Field>
        <Field label="Kdump Server">
          <input value={kdumpServer} onChange={(event) => setKdumpServer(event.target.value)} className="a4k-input" />
        </Field>
      </div>

      <div className="mt-4 rounded border border-slate-800 bg-slate-950/50 p-4">
        <div className="grid gap-4 lg:grid-cols-[1fr_auto]">
          <Field label="Server-side VMCore Path">
            <input
              value={vmcorePath}
              onChange={(event) => setVmcorePath(event.target.value)}
              className="a4k-input"
              placeholder="Leave empty when uploading a local vmcore"
            />
          </Field>
          <div className="flex items-end">
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={(event) => setSelectedVmcore(event.target.files?.[0] ?? null)}
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="flex h-10 items-center gap-2 rounded border border-blue-500/30 bg-blue-500/10 px-4 text-sm text-blue-200 hover:bg-blue-500/20"
            >
              <UploadCloud size={16} /> Upload VMCore
            </button>
          </div>
        </div>
        {selectedVmcore ? (
          <div className="mt-3 text-xs text-slate-400">
            Selected: <span className="font-mono text-slate-200">{selectedVmcore.name}</span>{" "}
            ({Math.ceil(selectedVmcore.size / 1024 / 1024)} MiB)
          </div>
        ) : null}
        {submitting && selectedVmcore ? (
          <div className="mt-3 h-2 overflow-hidden rounded bg-slate-800">
            <div className="h-full bg-blue-500 transition-all" style={{ width: `${uploadProgress}%` }} />
          </div>
        ) : null}
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-4">
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={enableRag} onChange={(event) => setEnableRag(event.target.checked)} />
          Enable RAG
        </label>
        <label className="flex items-center gap-2 text-sm text-slate-300">
          <input type="checkbox" checked={buildCodequery} onChange={(event) => setBuildCodequery(event.target.checked)} />
          Build CodeQuery
        </label>
      </div>

      <div className="mt-4 max-w-xs">
        <Field label="Agent Recursion Limit">
          <input
            type="number"
            min={1}
            value={recursionLimit}
            onChange={(event) => setRecursionLimit(Number(event.target.value) || 1)}
            className="a4k-input"
          />
        </Field>
      </div>

      {error ? <p className="mt-4 rounded border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">{error}</p> : null}

      <div className="mt-5 flex justify-end">
        <button
          type="submit"
          disabled={submitting}
          className="flex items-center gap-2 rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {submitting ? <Loader2 size={16} className="animate-spin" /> : <PlayCircle size={16} />}
          Create Session
        </button>
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </span>
      {children}
    </label>
  );
}

function Metric({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return (
    <section className="rounded-md border border-border bg-slate-900/60 p-4">
      <div className="flex items-center justify-between text-slate-500">
        <span className="text-xs uppercase tracking-widest">{label}</span>
        {icon}
      </div>
      <div className="mt-3 text-2xl font-bold text-slate-100">{value}</div>
    </section>
  );
}
