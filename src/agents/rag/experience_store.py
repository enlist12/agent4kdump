import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ExperienceStore:
    """Persist solved cases and maintain the markdown corpus used by RAG."""

    def __init__(self, base_dir: Path, logger: Any) -> None:
        self.base_dir = Path(base_dir)
        self.logger = logger
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.experience_jsonl = self.base_dir / "experience_store.jsonl"
        self.experience_docs_dir = self.base_dir / "experience_docs"
        self.experience_docs_dir.mkdir(parents=True, exist_ok=True)
        self.history_corpus_path = self.base_dir / "history_corpus.md"

    def load_records(self) -> list[dict[str, Any]]:
        if not self.experience_jsonl.exists():
            return []
        records: list[dict[str, Any]] = []
        for raw in self.experience_jsonl.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                records.append(json.loads(raw))
            except json.JSONDecodeError:
                self.logger.warning("Skipping malformed experience record line.")
        return records

    def persist_case(
        self,
        *,
        summary: str,
        root_cause: str,
        trigger_path: str,
        keywords: list[str],
        retrieval_text: str,
        trace_summary: dict[str, Any],
        lessons: dict[str, Any],
        profile: dict[str, Any],
        analysis_result: dict[str, Any],
        retrieved_context: dict[str, Any],
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        case_id = "case_" + hashlib.md5((now + retrieval_text).encode("utf-8")).hexdigest()[:12]
        record = {
            "case_id": case_id,
            "created_at": now,
            "summary": summary,
            "root_cause": root_cause,
            "trigger_path": trigger_path,
            "keywords": keywords,
            "retrieval_text": retrieval_text,
            "trace_summary": trace_summary,
            "lessons": lessons,
            "profile": profile,
            "analysis_result": analysis_result,
            "retrieved_context": retrieved_context,
        }
        with self.experience_jsonl.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        (self.experience_docs_dir / f"{case_id}.md").write_text(render_case_markdown(record), encoding="utf-8")
        self.logger.info("Persisted successful analysis case: %s", case_id)
        return case_id

    def build_history_corpus(self) -> dict[str, Any]:
        records = self.load_records()
        if not records:
            if self.history_corpus_path.exists():
                self.history_corpus_path.unlink()
            return {"exists": False, "record_count": 0, "corpus_hash": "", "corpus_path": self.history_corpus_path}
        content = "# Historical Kernel Crash Experience Corpus\n\n" + "\n\n".join(
            render_case_markdown(record, heading_level=2) for record in sorted(records, key=lambda item: str(item.get("created_at", "")))
        )
        content = content.strip() + "\n"
        self.history_corpus_path.write_text(content, encoding="utf-8")
        return {
            "exists": True,
            "record_count": len(records),
            "corpus_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "corpus_path": self.history_corpus_path,
        }


def render_case_markdown(record: dict[str, Any], heading_level: int = 1) -> str:
    lessons = record.get("lessons", {}) or {}
    analysis = record.get("analysis_result", {}) or {}
    h1 = "#" * heading_level
    h2 = "#" * (heading_level + 1)
    experience = [*lessons.get("reusable_playbook", []), *lessons.get("fix_patterns", [])]
    boundary = [*lessons.get("applicability", []), *lessons.get("non_applicability", [])]
    if lessons.get("evidence_boundary"):
        boundary.append(lessons["evidence_boundary"])
    return (
        f"{h1} {record.get('case_id', 'unknown_case')}\n\n"
        f"{h2} Experience Summary\n{lessons.get('case_signature') or record.get('summary', 'none')}\n\n"
        f"{h2} Root Cause Pattern\n{record.get('root_cause') or analysis.get('root_cause') or 'none'}\n\n"
        f"{h2} Trigger Pattern\n{record.get('trigger_path') or analysis.get('trigger_path') or 'none'}\n\n"
        f"{h2} Reusable Experience\n{bullet_list(experience)}\n\n"
        f"{h2} Reuse Boundary\n{bullet_list(boundary)}\n\n"
        f"{h2} Evidence\n{bullet_list(analysis.get('evidence', []) or [])}\n\n"
        f"{h2} Fix Suggestion\n{analysis.get('fix_suggestion') or 'none'}"
    )


def bullet_list(items: list[Any]) -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    return "\n".join(f"- {item}" for item in values) if values else "- none"
