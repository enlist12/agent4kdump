import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from dotenv import find_dotenv, load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

from log import get_logger
from runtime_config import get_invoke_config
from agents.utils.model import get_model

from .experience_store import ExperienceStore
from .linux_background import LinuxBackgroundCollector
from .pageindex_tree import PageIndexTreeRetriever

TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]+")
FUNC_RE = re.compile(r"\b([a-zA-Z_][a-zA-Z0-9_]+)\+0x[0-9a-f]+/0x[0-9a-f]+")
PATH_RE = re.compile(r"(drivers/[a-zA-Z0-9_./-]+)")

load_dotenv(find_dotenv())


class AnalysisRAGManager:
    """Build pre-analysis RAG context and persist solved crash experience."""

    def __init__(self, base_dir: str = "./cache/rag", use_pageindex: bool = True) -> None:
        self.logger = get_logger("analysis_rag")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.experience_store = ExperienceStore(self.base_dir, self.logger)
        self.pageindex_tree = PageIndexTreeRetriever(
            self.base_dir, self.logger, enabled=use_pageindex
        )
        self.linux_background = LinuxBackgroundCollector(self.logger)
        self.background_summarizer = get_model()
        self.corpus_info = self.experience_store.build_history_corpus()
        self.pageindex_tree.mark_corpus_state(self.corpus_info)
        self.pageindex_tree.sync_history_tree(self.corpus_info)
        status = self.get_pageindex_runtime_status()
        if status["tree_cache_ready"]:
            self.logger.info("PageIndex history tree ready.")
        elif status.get("last_sync_status") == "no_history":
            self.logger.info(
                "No historical experience stored yet; skipping history retrieval bootstrap."
            )
        else:
            self.logger.warning(
                "PageIndex history tree unavailable. %s", status.get("fallback_reason", "")
            )

    def build_pre_analysis_context(self, crash_report: str, top_k: int = 3) -> dict[str, Any]:
        profile = self._extract_profile(crash_report)
        query = " | ".join(
            [
                f"bug_type={profile.get('bug_type', 'unknown')}",
                f"kernel={profile.get('kernel_version', 'unknown')}",
                "drivers=" + ",".join(profile.get("driver_candidates", [])[:3]),
                "functions=" + ",".join(profile.get("functions", [])[:4]),
                "excerpt=" + shorten(crash_report.replace("\n", " "), 600),
            ]
        )
        self.corpus_info = self.experience_store.build_history_corpus()
        self.pageindex_tree.mark_corpus_state(self.corpus_info)
        self.pageindex_tree.sync_history_tree(self.corpus_info)
        status = self.pageindex_tree.get_runtime_status(self.corpus_info)
        experience_hits: list[dict[str, Any]] = []
        if status["tree_cache_ready"]:
            records = {
                str(item.get("case_id", "")): item for item in self.experience_store.load_records()
            }
            for hit in self.pageindex_tree.retrieve_from_tree(query, top_k):
                record = records.get(str(hit.get("case_id", "")))
                if not record:
                    experience_hits.append(hit)
                    continue
                lessons = record.get("lessons", {}) or {}
                experience_hits.append(
                    {
                        **hit,
                        "summary": record.get("summary", hit.get("summary", "")),
                        "root_cause": record.get("root_cause", ""),
                        "trigger_path": record.get("trigger_path", ""),
                        "case_signature": lessons.get("case_signature", ""),
                        "reusable_playbook": lessons.get("reusable_playbook", []),
                        "applicability": lessons.get("applicability", []),
                        "non_applicability": lessons.get("non_applicability", []),
                    }
                )
            if not experience_hits:
                query_tokens = set(tokenize(query))
                scored: list[dict[str, Any]] = []
                for rec in self.experience_store.load_records():
                    tokens = set(tokenize(str(rec.get("retrieval_text", ""))))
                    overlap = len(query_tokens & tokens)
                    if not overlap:
                        continue
                    lessons = rec.get("lessons", {}) or {}
                    keyword_boost = sum(
                        0.05 for kw in rec.get("keywords", []) if kw in query_tokens
                    )
                    scored.append(
                        {
                            "case_id": rec.get("case_id"),
                            "summary": rec.get("summary", ""),
                            "root_cause": rec.get("root_cause", ""),
                            "trigger_path": rec.get("trigger_path", ""),
                            "case_signature": lessons.get("case_signature", ""),
                            "reusable_playbook": lessons.get("reusable_playbook", []),
                            "applicability": lessons.get("applicability", []),
                            "non_applicability": lessons.get("non_applicability", []),
                            "score": overlap / max(len(query_tokens), 1) + keyword_boost,
                            "source": "local_store",
                        }
                    )
                experience_hits = sorted(scored, key=lambda item: item["score"], reverse=True)[
                    :top_k
                ]
        else:
            if status.get("fallback_reason"):
                self.logger.info("PageIndex tree unavailable: %s", status["fallback_reason"])
            query_tokens = set(tokenize(query))
            scored: list[dict[str, Any]] = []
            for rec in self.experience_store.load_records():
                tokens = set(tokenize(str(rec.get("retrieval_text", ""))))
                overlap = len(query_tokens & tokens)
                if not overlap:
                    continue
                lessons = rec.get("lessons", {}) or {}
                keyword_boost = sum(0.05 for kw in rec.get("keywords", []) if kw in query_tokens)
                scored.append(
                    {
                        "case_id": rec.get("case_id"),
                        "summary": rec.get("summary", ""),
                        "root_cause": rec.get("root_cause", ""),
                        "trigger_path": rec.get("trigger_path", ""),
                        "case_signature": lessons.get("case_signature", ""),
                        "reusable_playbook": lessons.get("reusable_playbook", []),
                        "applicability": lessons.get("applicability", []),
                        "non_applicability": lessons.get("non_applicability", []),
                        "score": overlap / max(len(query_tokens), 1) + keyword_boost,
                        "source": "local_store",
                    }
                )
            experience_hits = sorted(scored, key=lambda item: item["score"], reverse=True)[:top_k]
        linux_background = self.linux_background.collect(profile)
        background_summary = self._summarize_linux_background(profile, linux_background)
        experience = "\n\n".join(
            "\n".join(
                [
                    f"[{idx}] source={hit.get('source')} score={hit.get('score', 0):.3f}",
                    f"case_id={hit.get('case_id', '')}",
                    f"summary={hit.get('summary', '')}",
                    f"root_cause={hit.get('root_cause', '')}",
                    f"trigger_path={hit.get('trigger_path', '')}",
                    f"case_signature={hit.get('case_signature', '')}",
                    f"playbook={'; '.join(hit.get('reusable_playbook', []))}",
                    f"applicability={'; '.join(hit.get('applicability', []))}",
                    f"non_applicability={'; '.join(hit.get('non_applicability', []))}",
                    f"node_id={hit.get('node_id', '')}",
                    f"text={shorten(hit.get('text', ''), 500)}",
                ]
            )
            for idx, hit in enumerate(experience_hits, 1)
        )
        return {
            "profile": profile,
            "query": query,
            "experience_hits": experience_hits,
            "linux_background": linux_background,
            "linux_background_summary": background_summary,
            "context": (
                "Section 1: Similar Case Signatures\n"
                f"{experience or 'No historical experience retrieved.'}\n\n"
                "Section 2: Linux Module Background\n"
                f"{background_summary or 'No extra Linux background was collected.'}\n\n"
                "Section 3: Non-Transferable / Mismatch Warnings\n"
                "- Treat retrieved cases as workflow hints only; prove all conclusions in the current source.\n"
                "- Do not reuse old root causes unless object, path, and state transition match.\n\n"
                "Section 4: Suggested Checks For This Crash\n"
                f"- Start at bug_type={profile.get('bug_type', 'unknown')} and functions={', '.join(profile.get('functions', [])[:4]) or 'unknown'}.\n"
                "- Identify the immediate invalid object before using historical hints.\n"
                "- Trace one upstream hop at a time and keep file/function/line grounding.\n\n"
                "Section 5: Confidence Notes\n"
                "- RAG context is deterministic retrieval support, not evidence.\n"
                f"- Crash excerpt used for retrieval: {shorten(crash_report.replace(chr(10), ' '), 600)}"
            ),
        }

    def _summarize_linux_background(
        self, profile: dict[str, Any], linux_background: list[dict[str, str]]
    ) -> str:
        if not linux_background:
            return ""
        profile_text = "\n".join(
            [
                f"bug_type={profile.get('bug_type', 'unknown')}",
                f"kernel_version={profile.get('kernel_version', 'unknown')}",
                f"driver_candidates={', '.join(profile.get('driver_candidates', [])[:3]) or 'none'}",
                f"modules={', '.join(profile.get('modules', [])[:3]) or 'none'}",
                f"functions={', '.join(profile.get('functions', [])[:4]) or 'none'}",
            ]
        )
        background_text = "\n\n".join(
            [
                "\n".join(
                    [
                        f"[Source {idx}]",
                        f"url={item.get('url', '')}",
                        f"query={item.get('query', '')}",
                        f"content={shorten(str(item.get('content', '')), 1200)}",
                    ]
                )
                for idx, item in enumerate(linux_background[:3], 1)
            ]
        )
        system_prompt = (
            "You are summarizing Linux kernel subsystem background for crash root-cause analysis.\n"
            "Your job is to compress retrieved web pages into short analysis aids.\n"
            "Keep only information that helps understand subsystem behavior, function role, invariants, "
            "or relevant historical patch/discussion context.\n"
            "Do not infer the current crash root cause. Do not repeat generic kernel advice."
        )
        user_prompt = (
            "Summarize the retrieved background into at most 4 bullet lines.\n"
            "Each bullet must be short and source-anchored with `[S1]`, `[S2]`, or `[S3]`.\n"
            "Prefer these categories when supported by the text: subsystem responsibilities, key function semantics, "
            "important state/invariant expectations, historical patch or regression context.\n"
            "If the sources are weak or noisy, say that briefly instead of guessing.\n\n"
            f"Crash profile:\n{profile_text}\n\n"
            f"Retrieved sources:\n{background_text}"
        )
        try:
            response = self.background_summarizer.invoke(
                [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
                config=get_invoke_config(),
            )
            content = getattr(response, "content", str(response)).strip()
            return shorten(content, 900)
        except Exception as exc:
            self.logger.warning("background summarization failed: %s", exc)
            fallback_lines = [
                f"[S{idx}] {item.get('url', '')}"
                for idx, item in enumerate(linux_background[:2], 1)
                if item.get("url")
            ]
            return "\n".join(fallback_lines)

    def persist_success_case(
        self,
        crash_report: str,
        analysis_result: dict[str, Any],
        trace: Optional[dict[str, Any]] = None,
        retrieved_context: Optional[dict[str, Any]] = None,
    ) -> str:
        profile = self._extract_profile(crash_report)
        root_cause = str(analysis_result.get("root_cause", "")).strip()
        trigger_path = str(analysis_result.get("trigger_path", "")).strip()
        fix_suggestion = str(analysis_result.get("fix_suggestion", "")).strip()
        evidence = [str(item) for item in analysis_result.get("evidence", [])]
        counter: Counter[str] = Counter()
        samples: dict[str, str] = {}
        for call in (trace or {}).get("tool_calls", []):
            name = str(call.get("name", "unknown_tool"))
            counter[name] += 1
            samples.setdefault(
                name, shorten(json.dumps(call.get("args", {}), ensure_ascii=False), 140)
            )
        trace_summary = {
            "tool_usage": [
                {"name": name, "count": count, "sample_args": samples.get(name, "")}
                for name, count in counter.most_common(6)
            ],
            "tool_total_calls": sum(counter.values()),
            "taint_outline": [
                f"{idx + 1}. {item.get('current_function')}::{item.get('variable_name')} @ {item.get('file_name')}:{item.get('line')} end={item.get('end')}"
                for idx, item in enumerate((trace or {}).get("taint_chain", [])[:8])
            ],
            "last_node": (trace or {}).get("last_node", ""),
        }
        subsystem = ", ".join(profile.get("driver_candidates", [])[:3]) or "unknown subsystem"
        bug_type = profile.get("bug_type", "unknown")
        functions = ", ".join(profile.get("functions", [])[:4]) or "unknown functions"
        lessons = {
            "case_signature": shorten(f"{bug_type} in {subsystem}; functions={functions}", 240),
            "reusable_playbook": [
                "Anchor the first claim to the exact crash-site object and statement.",
                "Trace one upstream hop at a time until the first credible state boundary.",
                "Separate proven source facts from inferred propagation hypotheses.",
            ],
            "applicability": [
                f"Similar bug type ({bug_type}) in the same subsystem or source-path family.",
                "A taint chain with similar object ownership, initialization, or lifecycle transitions.",
            ],
            "non_applicability": [
                "Function names match but the invalid object or access mode differs.",
                "The previous case depended on a different configuration, caller, or lifetime boundary.",
            ],
            "fix_patterns": [
                "Add a guard or invariant check close to the dereference/use site.",
                "Repair earlier initialization or lifecycle handoff only when source evidence proves it.",
            ],
            "evidence_boundary": "Stored experience is a guide; current crash still requires source-grounded proof.",
            "tool_strategy": f"Used {trace_summary.get('tool_total_calls', 0)} tool calls; start with crash line, definitions, callers, and one-hop taint checks.",
        }
        retrieval_text = "\n".join(
            [
                f"BugType: {profile.get('bug_type', 'unknown')}",
                f"KernelVersion: {profile.get('kernel_version', 'unknown')}",
                f"DriverCandidates: {', '.join(profile.get('driver_candidates', [])) or 'none'}",
                f"Functions: {', '.join(profile.get('functions', [])) or 'none'}",
                f"RootCause: {root_cause}",
                f"TriggerPath: {trigger_path}",
                f"FixSuggestion: {fix_suggestion}",
                f"CaseSignature: {lessons['case_signature']}",
                f"ToolStrategy: {lessons['tool_strategy']}",
                "ReusablePlaybook:",
                *[f"- {item}" for item in lessons["reusable_playbook"]],
                "Applicability:",
                *[f"- {item}" for item in lessons["applicability"]],
                "NonApplicability:",
                *[f"- {item}" for item in lessons["non_applicability"]],
                "FixPatterns:",
                *[f"- {item}" for item in lessons["fix_patterns"]],
                f"EvidenceBoundary: {lessons['evidence_boundary']}",
                "Evidence:",
                *[f"- {item}" for item in evidence],
            ]
        )
        case_id = self.experience_store.persist_case(
            summary=shorten(" ".join([root_cause, trigger_path, fix_suggestion]), 280),
            root_cause=root_cause,
            trigger_path=trigger_path,
            keywords=profile.get("keywords", []),
            retrieval_text=retrieval_text,
            trace_summary=trace_summary,
            lessons=lessons,
            profile=profile,
            analysis_result=analysis_result,
            retrieved_context=retrieved_context or {},
        )
        self.corpus_info = self.experience_store.build_history_corpus()
        self.pageindex_tree.mark_corpus_state(self.corpus_info)
        return case_id

    def get_pageindex_runtime_status(self) -> dict[str, Any]:
        self.corpus_info = self.experience_store.build_history_corpus()
        self.pageindex_tree.mark_corpus_state(self.corpus_info)
        return self.pageindex_tree.get_runtime_status(self.corpus_info)

    def _extract_profile(self, crash_report: str) -> dict[str, Any]:
        functions = list(dict.fromkeys(FUNC_RE.findall(crash_report)))[:8]
        modules: list[str] = []
        for line in crash_report.splitlines():
            if "Modules linked in:" not in line:
                continue
            for token in line.split("Modules linked in:", 1)[1].split():
                cleaned = re.sub(r"\(.*?\)", "", token).strip(",")
                if cleaned and cleaned != "-":
                    modules.append(cleaned)
        modules = list(dict.fromkeys(modules))[:8]
        inferred_drivers = list(
            dict.fromkeys(
                fn.split("_", 1)[0]
                for fn in functions
                if "_" in fn and len(fn.split("_", 1)[0]) >= 3 and fn.split("_", 1)[0] != "kasan"
            )
        )
        drivers = list(dict.fromkeys(modules + inferred_drivers))[:6]
        if not drivers:
            drivers = list(
                dict.fromkeys(
                    path.split("/")[2]
                    for path in PATH_RE.findall(crash_report)
                    if len(path.split("/")) >= 3
                )
            )[:6]
        lower_report = crash_report.lower()
        bug_type = "unknown"
        for item in [
            "use-after-free",
            "null pointer dereference",
            "general protection fault",
            "kernel panic",
            "kasan",
            "out-of-bounds",
            "double free",
            "slab-out-of-bounds",
            "page fault",
        ]:
            if item in lower_report:
                bug_type = item
                break
        kernel_version = "unknown"
        for pattern in [
            r"Linux version\s+([^\s]+)",
            r"kernel version[:\s]+([^\s,]+)",
            r"\b(\d+\.\d+\.\d+[-\w.]*)\b",
        ]:
            match = re.search(pattern, crash_report, re.IGNORECASE)
            if match:
                kernel_version = match.group(1)
                break
        keywords = [
            item
            for item in [kernel_version, bug_type, *drivers, *functions[:5]]
            if item and item != "unknown"
        ]
        return {
            "kernel_version": kernel_version,
            "bug_type": bug_type,
            "functions": functions,
            "modules": modules,
            "driver_candidates": drivers,
            "keywords": keywords,
        }


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(text or ""))]


def shorten(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + " ..."
