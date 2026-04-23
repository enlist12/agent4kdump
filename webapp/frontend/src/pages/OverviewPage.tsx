import { useEffect, useState } from "react";
import { getProjectOverview, getProjectTree } from "../api";
import type { ProjectOverview, ProjectTreeNode } from "../types";

function TreeNode({ node }: { node: ProjectTreeNode }) {
  return (
    <li>
      <span className={`tree-pill ${node.type}`}>{node.name}</span>
      {node.children?.length ? (
        <ul className="tree-children">
          {node.children.map((child) => (
            <TreeNode key={`${child.path}-${child.name}`} node={child} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function OverviewPage() {
  const [overview, setOverview] = useState<ProjectOverview | null>(null);
  const [tree, setTree] = useState<ProjectTreeNode[]>([]);

  useEffect(() => {
    void Promise.all([getProjectOverview(), getProjectTree()]).then(([project, nodes]) => {
      setOverview(project);
      setTree(nodes);
    });
  }, []);

  return (
    <div className="overview-stack">
      <section className="hero-banner overview">
        <div>
          <p className="eyebrow">项目总览</p>
          <h2>从 vmcore 挂载、Known Bug Search、污点分析到经验沉淀的完整构成</h2>
        </div>
        <div className="hero-ribbon">
          <span>{overview?.total_cases ?? 0} Cases</span>
          <span>{overview?.total_experiences ?? 0} Experiences</span>
          <span>{overview?.syzbot_bug_files ?? 0} Bug Files</span>
        </div>
      </section>

      <div className="overview-grid">
        <section className="panel">
          <div className="panel-header">
            <p className="eyebrow">工作流</p>
            <span className="panel-aside">6 stages</span>
          </div>
          <div className="timeline-stack">
            {(overview?.workflow ?? []).map((item) => (
              <article key={item.name} className="timeline-card">
                <strong>{item.name}</strong>
                <p>{item.description}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="panel">
          <div className="panel-header">
            <p className="eyebrow">核心模块</p>
            <span className="panel-aside">{overview?.modules.length ?? 0} modules</span>
          </div>
          <div className="module-grid">
            {(overview?.modules ?? []).map((module) => (
              <article key={module.name} className="module-card">
                <strong>{module.name}</strong>
                <p>{module.description}</p>
                <code>{module.path}</code>
                {(module.children ?? []).map((child) => (
                  <div key={child.name} className="module-subcard">
                    <span>{child.name}</span>
                    <small>{child.description}</small>
                  </div>
                ))}
              </article>
            ))}
          </div>
        </section>
      </div>

      <section className="panel">
        <div className="panel-header">
          <p className="eyebrow">目录与数据树</p>
          <span className="panel-aside">{tree.length} roots</span>
        </div>
        <ul className="tree-root">
          {tree.map((node) => (
            <TreeNode key={node.path} node={node} />
          ))}
        </ul>
      </section>
    </div>
  );
}
