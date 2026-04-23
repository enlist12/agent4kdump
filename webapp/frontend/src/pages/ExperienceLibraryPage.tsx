import { useEffect, useMemo, useState } from "react";
import { getExperience, listExperiences } from "../api";
import type { ExperienceDetail, ExperienceRecord } from "../types";

export function ExperienceLibraryPage() {
  const [items, setItems] = useState<ExperienceRecord[]>([]);
  const [activeId, setActiveId] = useState("");
  const [detail, setDetail] = useState<ExperienceDetail | null>(null);
  const [query, setQuery] = useState("");
  const [confidence, setConfidence] = useState("all");

  useEffect(() => {
    void listExperiences().then((rows) => {
      setItems(rows);
      if (rows[0]) {
        setActiveId(rows[0].case_id);
        void getExperience(rows[0].case_id).then(setDetail);
      }
    });
  }, []);

  const filtered = useMemo(() => {
    return items.filter((item) => {
      const matchesQuery =
        !query ||
        [item.case_id, item.summary, item.root_cause, ...(item.keywords ?? [])]
          .join(" ")
          .toLowerCase()
          .includes(query.toLowerCase());
      const matchesConfidence = confidence === "all" || item.confidence === confidence;
      return matchesQuery && matchesConfidence;
    });
  }, [confidence, items, query]);

  return (
    <div className="two-column-layout">
      <section className="panel">
        <div className="panel-header">
          <p className="eyebrow">历史经验案例库</p>
          <span className="panel-aside">{filtered.length} cases</span>
        </div>

        <div className="filter-row">
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索 case_id / summary / keyword" />
          <select value={confidence} onChange={(event) => setConfidence(event.target.value)}>
            <option value="all">所有置信度</option>
            <option value="high">high</option>
            <option value="medium">medium</option>
            <option value="low">low</option>
          </select>
        </div>

        <div className="list-card-stack">
          {filtered.map((item) => (
            <button
              key={item.case_id}
              className={activeId === item.case_id ? "list-card active" : "list-card"}
              onClick={() => {
                setActiveId(item.case_id);
                void getExperience(item.case_id).then(setDetail);
              }}
            >
              <div className="list-card-header">
                <strong>{item.case_id}</strong>
                <span>{item.confidence}</span>
              </div>
              <p>{item.summary}</p>
              <div className="chip-row">
                {(item.driver_candidates ?? []).slice(0, 5).map((token) => (
                  <span key={token} className="chip">
                    {token}
                  </span>
                ))}
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <p className="eyebrow">案例详情</p>
          <span className="panel-aside">{detail?.case_id || "No selection"}</span>
        </div>
        {!detail ? (
          <div className="empty-state">选择左侧案例后查看根因、Trace、RAG 与 Markdown 卡片。</div>
        ) : (
          <div className="detail-stack">
            <div className="highlight-grid">
              <div className="highlight-card">
                <p className="metric-label">Root Cause</p>
                <strong>{detail.root_cause}</strong>
              </div>
              <div className="highlight-card">
                <p className="metric-label">Trigger Path</p>
                <strong>{detail.trigger_path}</strong>
              </div>
            </div>

            <div className="artifact-block">
              <div className="artifact-title">Analysis Result</div>
              <pre>{JSON.stringify(detail.analysis_result, null, 2)}</pre>
            </div>

            <div className="artifact-block">
              <div className="artifact-title">Trace Summary</div>
              <pre>{JSON.stringify(detail.trace_summary, null, 2)}</pre>
            </div>

            <div className="artifact-block">
              <div className="artifact-title">Markdown Card</div>
              <pre>{detail.markdown_content}</pre>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
