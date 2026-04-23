from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .models import (
    CaseRecordView,
    ExperienceDetailView,
    ExperienceRecordView,
    ProjectModuleView,
    ProjectOverviewView,
)


class ProjectRepository:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.case_dir = self.root_dir / "case"
        self.rag_dir = self.root_dir / "cache" / "rag"
        self.experience_jsonl = self.rag_dir / "experience_store.jsonl"
        self.experience_docs_dir = self.rag_dir / "experience_docs"
        self.config_path = self.root_dir / "config.yaml"
        self.pageindex_state_path = self.rag_dir / "pageindex_state.json"

    def load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {}
        return yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

    def list_cases(self) -> List[CaseRecordView]:
        if not self.case_dir.exists():
            return []

        records: List[CaseRecordView] = []
        for case_path in sorted([item for item in self.case_dir.iterdir() if item.is_dir()]):
            files = list(case_path.iterdir())
            vmcore_path = self._first_existing(case_path / "vmcore", case_path / "dump.img")
            poc_path = self._first_existing(case_path / "poc")
            poc_source_path = self._first_existing(case_path / "poc.c")
            config_path = self._first_existing(case_path / "config")
            mtime = max((item.stat().st_mtime for item in files), default=None)
            records.append(
                CaseRecordView(
                    case_id=case_path.name,
                    path=str(case_path),
                    vmcore_path=str(vmcore_path) if vmcore_path else None,
                    poc_path=str(poc_path) if poc_path else None,
                    poc_source_path=str(poc_source_path) if poc_source_path else None,
                    config_path=str(config_path) if config_path else None,
                    has_vmcore=vmcore_path is not None,
                    has_poc=poc_path is not None or poc_source_path is not None,
                    has_config=config_path is not None,
                    file_count=len(files),
                    updated_at=datetime.fromtimestamp(mtime) if mtime else None,
                    poc_preview=self._read_preview(poc_source_path or poc_path),
                    config_preview=self._read_preview(config_path),
                )
            )
        return records

    def get_case(self, case_id: str) -> Optional[CaseRecordView]:
        for record in self.list_cases():
            if record.case_id == case_id:
                return record
        return None

    def list_experiences(self) -> List[ExperienceRecordView]:
        rows = self._load_experience_rows()
        items: List[ExperienceRecordView] = []
        for row in rows:
            profile = row.get("profile", {}) or {}
            items.append(
                ExperienceRecordView(
                    case_id=str(row.get("case_id", "")),
                    created_at=self._parse_dt(row.get("created_at")),
                    summary=str(row.get("summary", "")),
                    root_cause=str(row.get("root_cause", "")),
                    trigger_path=str(row.get("trigger_path", "")),
                    confidence=str(row.get("confidence", "unknown")),
                    keywords=[str(item) for item in row.get("keywords", []) if str(item).strip()],
                    kernel_version=profile.get("kernel_version"),
                    bug_type=profile.get("bug_type"),
                    driver_candidates=[
                        str(item)
                        for item in profile.get("driver_candidates", [])
                        if str(item).strip()
                    ],
                    markdown_path=self._markdown_path(str(row.get("case_id", ""))),
                )
            )
        items.sort(
            key=lambda item: item.created_at.timestamp() if item.created_at else 0,
            reverse=True,
        )
        return items

    def get_experience(self, case_id: str) -> Optional[ExperienceDetailView]:
        rows = self._load_experience_rows()
        row = next((item for item in rows if str(item.get("case_id")) == case_id), None)
        if row is None:
            return None

        profile = row.get("profile", {}) or {}
        markdown_path = self.experience_docs_dir / f"{case_id}.md"
        markdown_content = ""
        if markdown_path.exists():
            markdown_content = markdown_path.read_text(encoding="utf-8")

        return ExperienceDetailView(
            case_id=case_id,
            created_at=self._parse_dt(row.get("created_at")),
            summary=str(row.get("summary", "")),
            root_cause=str(row.get("root_cause", "")),
            trigger_path=str(row.get("trigger_path", "")),
            confidence=str(row.get("confidence", "unknown")),
            keywords=[str(item) for item in row.get("keywords", []) if str(item).strip()],
            kernel_version=profile.get("kernel_version"),
            bug_type=profile.get("bug_type"),
            driver_candidates=[
                str(item) for item in profile.get("driver_candidates", []) if str(item).strip()
            ],
            markdown_path=str(markdown_path) if markdown_path.exists() else None,
            lessons=row.get("lessons", {}) or {},
            trace_summary=row.get("trace_summary", {}) or {},
            analysis_result=row.get("analysis_result", {}) or {},
            retrieved_context=row.get("retrieved_context", {}) or {},
            retrieval_text=str(row.get("retrieval_text", "")),
            markdown_content=markdown_content,
        )

    def build_project_overview(self) -> ProjectOverviewView:
        cases = self.list_cases()
        experiences = self.list_experiences()
        bug_files = len(list((self.root_dir / "data").glob("*.bug")))
        state = self._load_json(self.pageindex_state_path) or {}

        modules = [
            ProjectModuleView(
                name="Kdump Runtime",
                description="负责加载 vmcore、连接 kdump-gdbserver 与 gdb/mi，并抽取 crash report。",
                path=str(self.root_dir / "src" / "kdump_analyze"),
            ),
            ProjectModuleView(
                name="Search / Review Agents",
                description="检查崩溃是否属于已知漏洞，记录检索指纹、查询过程与候选匹配。",
                path=str(self.root_dir / "src" / "agents"),
            ),
            ProjectModuleView(
                name="Analysis Agents",
                description="执行 object analysis、taint analysis 与 root cause analysis。",
                path=str(self.root_dir / "src" / "agents"),
                children=[
                    ProjectModuleView(
                        name="Taint Tree",
                        description="维护污点传播路径与树形分析摘要。",
                        path=str(self.root_dir / "src" / "agents" / "taint_tree.py"),
                    )
                ],
            ),
            ProjectModuleView(
                name="RAG / Experience Store",
                description="构建历史经验检索、PageIndex 树缓存与分析经验落盘。",
                path=str(self.root_dir / "src" / "agents" / "rag"),
            ),
        ]

        workflow = [
            {"name": "配置确认", "description": "读取 config.yaml、case 输入和 RAG 配置"},
            {"name": "Kdump 初始化", "description": "拉起 kdump-gdbserver，挂载 GDB 与 codequery"},
            {"name": "Known Bug Search", "description": "搜索 syzbot / CVE / patch 线索"},
            {"name": "RAG 上下文", "description": "提取历史经验与 Linux 模块背景"},
            {"name": "Root Cause Analysis", "description": "构建 taint path 并形成根因与修复建议"},
            {"name": "经验持久化", "description": "将分析结果沉淀到经验库与 Markdown 卡片"},
        ]

        return ProjectOverviewView(
            root_path=str(self.root_dir),
            config_path=str(self.config_path),
            total_cases=len(cases),
            total_experiences=len(experiences),
            syzbot_bug_files=bug_files,
            rag_status=state,
            workflow=workflow,
            modules=modules,
        )

    def build_project_tree(self) -> List[Dict[str, Any]]:
        targets = [
            self.root_dir / "src" / "kdump_analyze",
            self.root_dir / "src" / "agents",
            self.root_dir / "src" / "agents" / "rag",
            self.root_dir / "case",
            self.root_dir / "cache" / "rag",
            self.root_dir / "docs",
        ]
        return [self._tree_node(path, max_depth=2) for path in targets if path.exists()]

    def _tree_node(self, path: Path, max_depth: int, current_depth: int = 0) -> Dict[str, Any]:
        node = {
            "name": path.name,
            "path": str(path),
            "type": "directory" if path.is_dir() else "file",
        }
        if not path.is_dir() or current_depth >= max_depth:
            return node

        children = sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name))
        node["children"] = [
            self._tree_node(child, max_depth=max_depth, current_depth=current_depth + 1)
            for child in children[:24]
        ]
        if len(children) > 24:
            node["children"].append(
                {
                    "name": f"... {len(children) - 24} more",
                    "path": str(path),
                    "type": "truncated",
                }
            )
        return node

    def _load_experience_rows(self) -> List[Dict[str, Any]]:
        if not self.experience_jsonl.exists():
            return []
        rows: List[Dict[str, Any]] = []
        with self.experience_jsonl.open("r", encoding="utf-8") as handle:
            for raw in handle:
                line = raw.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    @staticmethod
    def _read_preview(path: Optional[Path], limit: int = 1200) -> Optional[str]:
        if path is None or not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[:limit] + "\n..."

    @staticmethod
    def _load_json(path: Path) -> Optional[Dict[str, Any]]:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            return None

    @staticmethod
    def _first_existing(*paths: Path) -> Optional[Path]:
        for path in paths:
            if path.exists():
                return path
        return None

    def _markdown_path(self, case_id: str) -> Optional[str]:
        if not case_id:
            return None
        path = self.experience_docs_dir / f"{case_id}.md"
        return str(path) if path.exists() else None
