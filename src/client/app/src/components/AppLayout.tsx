import {
  Activity,
  BookOpen,
  FileSearch,
  LayoutDashboard,
  Network,
  PlayCircle,
  Settings,
  Terminal
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { platform } from "../platform/adapter";

interface AppLayoutProps {
  children: ReactNode;
  activeTab: string;
  onTabChange: (tab: string) => void;
  sessionName?: string;
  status?: string;
}

const navItems = [
  { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { id: "analysis", label: "Active Analysis", icon: PlayCircle },
  { id: "search", label: "Search Results", icon: FileSearch },
  { id: "taint", label: "Taint Tree", icon: Network },
  { id: "reports", label: "Reports", icon: BookOpen }
];

function formatUptime(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`;
  }
  return `${minutes}m ${seconds}s`;
}

export function AppLayout({
  children,
  activeTab,
  onTabChange,
  sessionName = "No session selected",
  status = "idle"
}: AppLayoutProps) {
  const startedAt = useRef(Date.now());
  const [uptimeSeconds, setUptimeSeconds] = useState(0);
  const apiBaseUrl = useMemo(() => platform.getBaseUrl(), []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      setUptimeSeconds(Math.floor((Date.now() - startedAt.current) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-950 text-slate-100">
      <aside className="flex w-16 shrink-0 flex-col items-center border-r border-border bg-slate-950 py-4">
        <div className="mb-8 rounded-md bg-blue-600 p-2">
          <Activity size={24} className="text-white" />
        </div>

        <nav className="flex flex-1 flex-col gap-3">
          {navItems.map((item) => (
            <NavIcon
              key={item.id}
              icon={<item.icon size={20} />}
              active={activeTab === item.id}
              onClick={() => onTabChange(item.id)}
              tooltip={item.label}
            />
          ))}
        </nav>

        <NavIcon
          icon={<Settings size={20} />}
          active={activeTab === "settings"}
          onClick={() => onTabChange("settings")}
          tooltip="Settings"
        />
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-panel px-6">
          <div className="flex items-center gap-3 text-sm">
            <span className="font-mono text-slate-300">{sessionName}</span>
            <span className="rounded border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold uppercase text-emerald-400">
              {status}
            </span>
          </div>
          <div className="flex items-center gap-3">
            <button className="rounded border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs text-slate-200 transition hover:bg-slate-700">
              Export Report
            </button>
            <button className="rounded border border-red-500/30 bg-red-600/20 px-3 py-1.5 text-xs text-red-300 transition hover:bg-red-600/30">
              Stop Analysis
            </button>
          </div>
        </header>

        <section className="min-h-0 flex-1 overflow-hidden">{children}</section>

        <footer className="flex h-8 shrink-0 items-center justify-between border-t border-border bg-slate-950 px-4 text-[11px] text-slate-500">
          <div className="flex items-center gap-5">
            <span className="flex items-center gap-1">
              <Terminal size={12} /> API: {apiBaseUrl}
            </span>
            <span>Runtime: {platform.kind}</span>
          </div>
          <div className="flex items-center gap-5">
            <span>Uptime: {formatUptime(uptimeSeconds)}</span>
            <span className="text-blue-400">v0.1.0</span>
          </div>
        </footer>
      </main>
    </div>
  );
}

function NavIcon({
  icon,
  active,
  onClick,
  tooltip
}: {
  icon: ReactNode;
  active: boolean;
  onClick: () => void;
  tooltip: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`group relative rounded-md p-3 transition ${
        active
          ? "bg-blue-600 text-white shadow-lg shadow-blue-950/40"
          : "text-slate-500 hover:bg-slate-900 hover:text-slate-200"
      }`}
      aria-label={tooltip}
    >
      {icon}
      <span className="pointer-events-none absolute left-full top-1/2 z-50 ml-4 -translate-y-1/2 whitespace-nowrap rounded bg-slate-800 px-2 py-1 text-xs text-white opacity-0 shadow-lg transition group-hover:opacity-100">
        {tooltip}
      </span>
    </button>
  );
}
