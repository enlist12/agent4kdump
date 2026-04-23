import { useEffect, useState } from "react";
import { getCase, listCases } from "../api";
import type { CaseRecord } from "../types";

export function CasesPage() {
  const [cases, setCases] = useState<CaseRecord[]>([]);
  const [detail, setDetail] = useState<CaseRecord | null>(null);

  useEffect(() => {
    void listCases().then((rows) => {
      setCases(rows);
      if (rows[0]) {
        void getCase(rows[0].case_id).then(setDetail);
      }
    });
  }, []);

  return (
    <div className="two-column-layout">
      <section className="panel">
        <div className="panel-header">
          <p className="eyebrow">Case 输入集合</p>
          <span className="panel-aside">{cases.length} cases</span>
        </div>
        <div className="list-card-stack">
          {cases.map((record) => (
            <button key={record.case_id} className={detail?.case_id === record.case_id ? "list-card active" : "list-card"} onClick={() => void getCase(record.case_id).then(setDetail)}>
              <div className="list-card-header">
                <strong>{record.case_id}</strong>
                <span>{record.file_count} files</span>
              </div>
              <div className="chip-row">
                {record.has_vmcore ? <span className="chip">vmcore</span> : null}
                {record.has_poc ? <span className="chip">poc</span> : null}
                {record.has_config ? <span className="chip">config</span> : null}
              </div>
            </button>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <p className="eyebrow">Case 详情</p>
          <span className="panel-aside">{detail?.case_id || "No selection"}</span>
        </div>
        {!detail ? (
          <div className="empty-state">选择左侧 case 以查看 vmcore、POC 和配置预览。</div>
        ) : (
          <div className="detail-stack">
            <div className="highlight-grid">
              <div className="highlight-card">
                <p className="metric-label">VMCore</p>
                <strong>{detail.vmcore_path || "missing"}</strong>
              </div>
              <div className="highlight-card">
                <p className="metric-label">POC Source</p>
                <strong>{detail.poc_source_path || detail.poc_path || "missing"}</strong>
              </div>
            </div>

            {detail.poc_preview ? (
              <div className="artifact-block">
                <div className="artifact-title">POC Preview</div>
                <pre>{detail.poc_preview}</pre>
              </div>
            ) : null}

            {detail.config_preview ? (
              <div className="artifact-block">
                <div className="artifact-title">Config Preview</div>
                <pre>{detail.config_preview}</pre>
              </div>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
