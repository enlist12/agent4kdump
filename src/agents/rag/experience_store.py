import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


class ExperienceStore:
    """Persist solved cases and maintain markdown corpus for retrieval."""

    def __init__(self, base_dir: Path, logger: Any) -> None:
        self.base_dir = Path(base_dir)
        self.logger = logger
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.experience_jsonl = self.base_dir / "experience_store.jsonl"
        self.experience_docs_dir = self.base_dir / "experience_docs"
        self.experience_docs_dir.mkdir(parents=True, exist_ok=True)
        self.history_corpus_path = self.base_dir / "history_corpus.md"

    def load_records(self) -> List[Dict[str, Any]]:
        """Load persisted case records from jsonl store."""
        if not self.experience_jsonl.exists():
            return []

        records: List[Dict[str, Any]] = []
        with self.experience_jsonl.open("r", encoding="utf-8") as fp:
            for raw in fp:
                line = raw.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    self.logger.warning("Skipping malformed experience record line.")
        return records

    def persist_case(
        self,
        *,
        summary: str,
        root_cause: str,
        trigger_path: str,
        confidence: str,
        keywords: List[str],
        retrieval_text: str,
        trace_summary: Dict[str, Any],
        lessons: Dict[str, Any],
        profile: Dict[str, Any],
        analysis_result: Dict[str, Any],
        retrieved_context: Dict[str, Any],
    ) -> str:
        """Persist one solved case to jsonl and markdown card."""
        now_iso = datetime.now(timezone.utc).isoformat()
        case_hash = hashlib.md5((now_iso + retrieval_text).encode("utf-8")).hexdigest()[:12]
        case_id = f"case_{case_hash}"

        storage_obj = {
            "case_id": case_id,
            "created_at": now_iso,
            "summary": summary,
            "root_cause": root_cause,
            "trigger_path": trigger_path,
            "confidence": confidence,
            "keywords": keywords,
            "retrieval_text": retrieval_text,
            "trace_summary": trace_summary,
            "lessons": lessons,
            "profile": profile,
            "analysis_result": analysis_result,
            "retrieved_context": retrieved_context,
        }

        with self.experience_jsonl.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(storage_obj, ensure_ascii=False) + "\n")

        md_path = self.experience_docs_dir / f"{case_id}.md"
        md_path.write_text(self._render_case_markdown(storage_obj), encoding="utf-8")

        self.logger.info("Persisted successful analysis case: %s", case_id)
        return case_id

    def build_history_corpus(self) -> Dict[str, Any]:
        """Build a single aggregated markdown corpus for PageIndex tree generation."""
        records = self.load_records()
        if not records:
            if self.history_corpus_path.exists():
                self.history_corpus_path.unlink()
            return {
                "exists": False,
                "record_count": 0,
                "corpus_hash": "",
                "corpus_path": self.history_corpus_path,
            }

        content = self._render_history_corpus(records)
        self.history_corpus_path.write_text(content, encoding="utf-8")

        return {
            "exists": True,
            "record_count": len(records),
            "corpus_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "corpus_path": self.history_corpus_path,
        }

    @staticmethod
    def _render_history_corpus(records: List[Dict[str, Any]]) -> str:
        sections = ["# Historical Kernel Crash Experience Corpus", ""]

        def bullet_list(items: List[str]) -> str:
            filtered = [str(item).strip() for item in items if str(item).strip()]
            if not filtered:
                return "- none"
            return "\n".join(f"- {item}" for item in filtered)

        sorted_records = sorted(records, key=lambda item: str(item.get("created_at", "")))
        for record in sorted_records:
            lessons = record.get("lessons", {}) or {}
            profile = record.get("profile", {}) or {}
            analysis_result = record.get("analysis_result", {}) or {}
            reuse_boundary = [
                *lessons.get("applicability", []),
                *lessons.get("non_applicability", []),
            ]
            evidence_boundary = str(lessons.get("evidence_boundary", "")).strip()
            if evidence_boundary:
                reuse_boundary.append(evidence_boundary)
            experience_notes = [
                *lessons.get("reusable_playbook", []),
                *lessons.get("fix_patterns", []),
            ]

            sections.extend(
                [
                    f"## {record.get('case_id', 'unknown_case')}",
                    "",
                    "### Metadata",
                    f"- confidence: {record.get('confidence', 'unknown')}",
                    f"- kernel_version: {profile.get('kernel_version', 'unknown')}",
                    f"- bug_type: {profile.get('bug_type', 'unknown')}",
                    f"- driver_candidates: {', '.join(profile.get('driver_candidates', [])) or 'none'}",
                    f"- keywords: {', '.join(record.get('keywords', [])) or 'none'}",
                    "",
                    "### Experience Summary",
                    str(lessons.get("case_signature", "")).strip()
                    or str(record.get("summary", "")).strip()
                    or "none",
                    "",
                    "### Root Cause Pattern",
                    str(record.get("root_cause", "")).strip() or "none",
                    "",
                    "### Trigger Pattern",
                    str(record.get("trigger_path", "")).strip() or "none",
                    "",
                    "### Crash Site",
                    f"- file: {(analysis_result.get('crash_site') or {}).get('file', 'unknown')}",
                    f"- function: {(analysis_result.get('crash_site') or {}).get('function', 'unknown')}",
                    f"- line: {(analysis_result.get('crash_site') or {}).get('line', 'unknown')}",
                    f"- invalid_object: {(analysis_result.get('crash_site') or {}).get('invalid_object', 'unknown')}",
                    "",
                    "### Key Locations",
                    bullet_list(
                        [
                            (
                                f"role={item.get('role')} {item.get('file')}:{item.get('line')} "
                                f"{item.get('function')}::{item.get('object')} => {item.get('detail')}"
                            )
                            for item in analysis_result.get("key_locations", [])
                            if isinstance(item, dict)
                        ]
                    ),
                    "",
                    "### Reusable Experience",
                    bullet_list(experience_notes),
                    "",
                    "### Reuse Boundary",
                    bullet_list(reuse_boundary),
                    "",
                    "### Evidence",
                    bullet_list(analysis_result.get("evidence", []) or []),
                    "",
                    "### Fix Suggestion",
                    str(analysis_result.get("fix_suggestion", "")).strip() or "none",
                    "",
                ]
            )

        return "\n".join(sections).strip() + "\n"

    @staticmethod
    def _render_case_markdown(storage_obj: Dict[str, Any]) -> str:
        """Render one stored experience into a readable markdown card."""
        analysis_result = storage_obj.get("analysis_result", {}) or {}
        profile = storage_obj.get("profile", {}) or {}
        lessons = storage_obj.get("lessons", {}) or {}
        reuse_boundary = [
            *lessons.get("applicability", []),
            *lessons.get("non_applicability", []),
        ]
        evidence_boundary = str(lessons.get("evidence_boundary", "")).strip()
        if evidence_boundary:
            reuse_boundary.append(evidence_boundary)
        experience_notes = [
            *lessons.get("reusable_playbook", []),
            *lessons.get("fix_patterns", []),
        ]

        def bullet_list(items: List[str]) -> str:
            filtered = [str(item).strip() for item in items if str(item).strip()]
            if not filtered:
                return "- none"
            return "\n".join(f"- {item}" for item in filtered)

        crash_site = analysis_result.get("crash_site", {}) or {}
        crash_site_text = (
            f"- file: {crash_site.get('file', 'unknown')}\n"
            f"- function: {crash_site.get('function', 'unknown')}\n"
            f"- line: {crash_site.get('line', 'unknown')}\n"
            f"- invalid_object: {crash_site.get('invalid_object', 'unknown')}\n"
            f"- statement: {crash_site.get('statement', 'unknown')}"
        )
        key_location_text = bullet_list(
            [
                (
                    f"role={item.get('role')} {item.get('file')}:{item.get('line')} "
                    f"{item.get('function')}::{item.get('object')} => {item.get('detail')}"
                )
                for item in analysis_result.get("key_locations", [])
                if isinstance(item, dict)
            ]
        )

        return (
            f"# {storage_obj.get('case_id')}\n\n"
            f"- confidence: {analysis_result.get('confidence', 'unknown')}\n"
            f"- kernel_version: {profile.get('kernel_version', 'unknown')}\n"
            f"- bug_type: {profile.get('bug_type', 'unknown')}\n"
            f"- driver_candidates: {', '.join(profile.get('driver_candidates', [])) or 'none'}\n\n"
            "## Experience Summary\n"
            f"{lessons.get('case_signature', '') or storage_obj.get('summary', '')}\n\n"
            "## Root Cause Pattern\n"
            f"{analysis_result.get('root_cause', '')}\n\n"
            "## Crash Site\n"
            f"{crash_site_text}\n\n"
            "## Trigger Pattern\n"
            f"{analysis_result.get('trigger_path', '')}\n\n"
            "## Key Locations\n"
            f"{key_location_text}\n\n"
            "## Reusable Experience\n"
            f"{bullet_list(experience_notes)}\n\n"
            "## Reuse Boundary\n"
            f"{bullet_list(reuse_boundary)}\n\n"
            "## Evidence\n"
            f"{bullet_list(analysis_result.get('evidence', []) or [])}\n\n"
            "## Fix Suggestion\n"
            f"{analysis_result.get('fix_suggestion', '')}\n"
        )
