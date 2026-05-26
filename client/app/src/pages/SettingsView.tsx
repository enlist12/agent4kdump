import { useQuery } from "@tanstack/react-query";
import { FileInput, KeyRound, Loader2, Save } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { getEnvSettings, loadEnvFile, updateEnvSettings } from "../api/client";
import { platform } from "../platform/adapter";

const fields = [
  ["MODEL_PROVIDER", "Model Provider", "openai"],
  ["MODEL_NAME", "Model Name", "gpt-4o"],
  ["API_KEY", "Primary LLM API Key", "sk-..."],
  ["LLM_BASE_URL", "LLM Base URL", "https://api.openai.com/v1"],
  ["TAVILY_API_KEY", "Tavily API Key", "tvly-..."],
  ["LANGFUSE_PUBLIC_KEY", "Langfuse Public Key", "pk-..."],
  ["LANGFUSE_SECRET_KEY", "Langfuse Secret Key", "sk-..."],
  ["LANGFUSE_HOST", "Langfuse Host", "https://cloud.langfuse.com"],
  ["PAGEINDEX_API_KEY", "PageIndex API Key", ""],
  ["OPENAI_API_KEY", "OpenAI API Key", "sk-..."],
  ["OPENAI_API_BASE", "OpenAI API Base", "https://api.openai.com/v1"],
  ["DEEPSEEK_API_KEY", "DeepSeek API Key", "sk-..."],
  ["MODEL_TEMPERATURE", "Model Temperature", "0"],
  ["MAX_RECURSION_DEPTH", "Max Recursion Depth", "80"],
  ["SHELL_TOOL_WORKSPACE_ROOT", "Shell Workspace Root", ""]
] as const;

export function SettingsView() {
  const settingsQuery = useQuery({
    queryKey: ["env-settings"],
    queryFn: getEnvSettings,
    retry: 1
  });
  const [values, setValues] = useState<Record<string, string>>({});
  const [envPath, setEnvPath] = useState("");
  const [saving, setSaving] = useState(false);
  const [loadingEnv, setLoadingEnv] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!settingsQuery.data) {
      return;
    }
    const next: Record<string, string> = {};
    for (const [key] of fields) {
      next[key] = "";
    }
    setValues(next);
    setEnvPath(settingsQuery.data.path);
  }, [settingsQuery.data]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setMessage("");
    try {
      const payload: Record<string, string | null> = {};
      for (const [key] of fields) {
        if (values[key]?.trim()) {
          payload[key] = values[key].trim();
        }
      }
      await updateEnvSettings(payload);
      setValues(Object.fromEntries(fields.map(([key]) => [key, ""])));
      await settingsQuery.refetch();
      setMessage("Saved .env settings. New analysis sessions will use the updated environment.");
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Failed to save settings.");
    } finally {
      setSaving(false);
    }
  }

  async function chooseEnvFile() {
    const path = await platform.pickPath("file");
    if (path) {
      setEnvPath(path);
    }
  }

  async function loadExistingEnv() {
    if (!envPath.trim()) {
      setMessage("Choose or enter an existing .env path first.");
      return;
    }
    setLoadingEnv(true);
    setMessage("");
    try {
      await loadEnvFile(envPath.trim());
      await settingsQuery.refetch();
      setValues(Object.fromEntries(fields.map(([key]) => [key, ""])));
      setMessage("Loaded existing .env file. New analysis sessions will use this file.");
    } catch (cause) {
      setMessage(cause instanceof Error ? cause.message : "Failed to load .env file.");
    } finally {
      setLoadingEnv(false);
    }
  }

  return (
    <div className="a4k-scrollbar h-full overflow-y-auto bg-slate-950 p-6">
      <div className="mb-6">
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-100">
          <KeyRound size={24} /> Client Settings
        </h1>
        <p className="mt-1 text-sm text-slate-500">
          Configure the local `.env` used by the bundled backend and analysis agents.
        </p>
      </div>

      <section className="mb-5 rounded-md border border-border bg-slate-900/60 p-4">
        <div className="text-xs uppercase tracking-widest text-slate-500">Env File</div>
        <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_auto_auto]">
          <input
            value={envPath}
            onChange={(event) => setEnvPath(event.target.value)}
            className="a4k-input font-mono"
            placeholder="Select or type an existing .env file path"
          />
          <button
            type="button"
            onClick={() => void chooseEnvFile()}
            className="flex h-10 items-center gap-2 rounded border border-slate-700 bg-slate-800 px-3 text-sm text-slate-200 hover:bg-slate-700"
          >
            <FileInput size={16} /> Browse
          </button>
          <button
            type="button"
            onClick={() => void loadExistingEnv()}
            disabled={loadingEnv}
            className="flex h-10 items-center gap-2 rounded border border-blue-500/30 bg-blue-500/10 px-3 text-sm text-blue-100 hover:bg-blue-500/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loadingEnv ? <Loader2 size={16} className="animate-spin" /> : <FileInput size={16} />}
            Load Existing .env
          </button>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          The selected path is remembered by the client and used before config validation or analysis.
        </p>
      </section>

      <form onSubmit={submit} className="rounded-md border border-border bg-slate-900/60 p-4">
        <div className="grid gap-4 lg:grid-cols-2">
          {fields.map(([key, label, placeholder]) => {
            const current = settingsQuery.data?.values[key];
            return (
              <label key={key} className="block">
                <div className="mb-1 flex items-center justify-between gap-3">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    {label}
                  </span>
                  <span className="font-mono text-[11px] text-slate-600">
                    {current?.configured ? current.masked : "not set"}
                  </span>
                </div>
                <input
                  value={values[key] ?? ""}
                  onChange={(event) => setValues((state) => ({ ...state, [key]: event.target.value }))}
                  className="a4k-input"
                  placeholder={current?.configured ? "Leave blank to keep current value" : placeholder}
                  type={key.includes("KEY") || key.includes("SECRET") ? "password" : "text"}
                />
              </label>
            );
          })}
        </div>

        {message ? (
          <p className="mt-4 rounded border border-blue-500/30 bg-blue-500/10 p-3 text-sm text-blue-100">
            {message}
          </p>
        ) : null}

        <div className="mt-5 flex justify-end">
          <button
            type="submit"
            disabled={saving}
            className="flex items-center gap-2 rounded bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
            Save .env
          </button>
        </div>
      </form>
    </div>
  );
}
