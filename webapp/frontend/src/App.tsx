import { NavLink, Route, Routes } from "react-router-dom";
import { CasesPage } from "./pages/CasesPage";
import { ExperienceLibraryPage } from "./pages/ExperienceLibraryPage";
import { OverviewPage } from "./pages/OverviewPage";
import { WorkspacePage } from "./pages/WorkspacePage";

const NAV_ITEMS = [
  { to: "/", label: "分析工作台" },
  { to: "/experience", label: "历史经验库" },
  { to: "/cases", label: "案例与数据源" },
  { to: "/overview", label: "项目总览" },
];

export default function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand-block">
          <span className="brand-badge">AGENT4KDUMP</span>
          <h1>Visualization</h1>
        </div>
        <nav className="top-nav">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} end={item.to === "/"} className={({ isActive }) => (isActive ? "nav-link active" : "nav-link")}>
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>

      <main className="app-content">
        <Routes>
          <Route path="/" element={<WorkspacePage />} />
          <Route path="/experience" element={<ExperienceLibraryPage />} />
          <Route path="/cases" element={<CasesPage />} />
          <Route path="/overview" element={<OverviewPage />} />
        </Routes>
      </main>
    </div>
  );
}
