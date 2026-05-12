import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import find_dotenv, load_dotenv
from langchain.agents import create_agent
from langchain.messages import HumanMessage
from pydantic import BaseModel, Field

from agent_core.model import MAX_RECURSION_DEPTH, get_model
from agent_core.tools.commandTools import build_shell_middleware
from log import get_logger

from .experience_store import ExperienceStore
from .linux_background import LinuxBackgroundCollector
from .pageindex_tree import PageIndexTreeRetriever


TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]+")

load_dotenv(find_dotenv())


class RAGSummaryResult(BaseModel):
    historical_experience_insights: str = Field(
        description="Actionable patterns extracted from historical analysis experience."
    )
    linux_module_background: str = Field(
        description="Relevant Linux kernel module, subsystem, or driver background."
    )
    analysis_checklist: List[str] = Field(
        description="Concrete checks for the analyze agent before concluding root cause."
    )
    confidence_notes: str = Field(
        description="Confidence and caveats, especially when retrieval evidence is weak."
    )


class CrashProfileExtractionResult(BaseModel):
    kernel_version: Optional[str] = Field(default=None)
    bug_type: Optional[str] = Field(default=None)
    functions: List[str] = Field(default_factory=list)
    modules: List[str] = Field(default_factory=list)
    driver_candidates: List[str] = Field(default_factory=list)


class ExperienceLessonsResult(BaseModel):
    case_signature: str = Field(
        description="Compact case signature describing the crash shape and subsystem."
    )
    reusable_playbook: List[str] = Field(
        description="Transferable analysis steps to apply to similar crashes."
    )
    applicability: List[str] = Field(
        description="Signals suggesting this experience is applicable."
    )
    non_applicability: List[str] = Field(
        description="Signals suggesting this experience should not be reused directly."
    )
    fix_patterns: List[str] = Field(
        description="Common fix directions or patch patterns for this crash shape."
    )
    evidence_boundary: str = Field(
        description="What was proven in the current case versus what remained inferred."
    )
    tool_strategy: str = Field(
        description="A short strategy summary of which tools were useful and why."
    )


class AnalysisRAGManager:
    """Build pre-analysis RAG context and persist successful analysis experience."""

    def __init__(self, base_dir: str = "./cache/rag", use_pageindex: bool = True) -> None:
        self.logger = get_logger("analysis_rag")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.experience_store = ExperienceStore(base_dir=self.base_dir, logger=self.logger)
        self.pageindex_tree = PageIndexTreeRetriever(
            base_dir=self.base_dir,
            logger=self.logger,
            enabled=use_pageindex,
        )
        self.linux_background = LinuxBackgroundCollector(logger=self.logger)

        self.summary_agent = self._create_summary_agent()
        self.profile_agent = self._create_profile_agent()
        self.lessons_agent = self._create_lessons_agent()

        self.corpus_info = self.experience_store.build_history_corpus()
        self.pageindex_tree.mark_corpus_state(self.corpus_info)
        self.pageindex_tree.sync_history_tree(self.corpus_info)
        self._log_pageindex_status()

    def build_pre_analysis_context(self, crash_report: str, top_k: int = 3) -> Dict[str, Any]:
        """Build retrieval context before analyze-agent runs."""
        profile = self._extract_profile(crash_report)
        query = self._build_query(profile, crash_report)

        self.corpus_info = self.experience_store.build_history_corpus()
        self.pageindex_tree.mark_corpus_state(self.corpus_info)

        experience_hits = self._retrieve_experiences(query=query, top_k=top_k)
        linux_background = self.linux_background.collect(profile)
        final_context = self._summarize_context(
            crash_report=crash_report,
            profile=profile,
            experience_hits=experience_hits,
            linux_background=linux_background,
        )

        return {
            "profile": profile,
            "query": query,
            "experience_hits": experience_hits,
            "linux_background": linux_background,
            "context": final_context,
        }

    def persist_success_case(
        self,
        crash_report: str,
        analysis_result: Dict[str, Any],
        trace: Optional[Dict[str, Any]] = None,
        retrieved_context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist one solved case as compact, reusable experience."""
        profile = self._extract_profile(crash_report)
        root_cause = str(analysis_result.get("root_cause", "")).strip()
        trigger_path = str(analysis_result.get("trigger_path", "")).strip()
        evidence = analysis_result.get("evidence", [])
        fix_suggestion = str(analysis_result.get("fix_suggestion", "")).strip()

        summary = self._shorten(" ".join([root_cause, trigger_path, fix_suggestion]), limit=280)
        keywords = profile.get("keywords", [])
        trace_summary = self._summarize_trace(trace or {})
        lessons = self._distill_experience_lessons(
            profile=profile,
            analysis_result=analysis_result,
            trace_summary=trace_summary,
        )

        retrieval_text = "\n".join(
            [
                f"BugType: {profile.get('bug_type', 'unknown')}",
                f"KernelVersion: {profile.get('kernel_version', 'unknown')}",
                f"DriverCandidates: {', '.join(profile.get('driver_candidates', [])) or 'none'}",
                f"Functions: {', '.join(profile.get('functions', [])) or 'none'}",
                f"RootCause: {root_cause}",
                f"TriggerPath: {trigger_path}",
                f"FixSuggestion: {fix_suggestion}",
                f"CaseSignature: {lessons.get('case_signature', '')}",
                f"ToolStrategy: {lessons.get('tool_strategy', '')}",
                "ReusablePlaybook:",
                *[f"- {item}" for item in lessons.get("reusable_playbook", [])],
                "Applicability:",
                *[f"- {item}" for item in lessons.get("applicability", [])],
                "NonApplicability:",
                *[f"- {item}" for item in lessons.get("non_applicability", [])],
                "FixPatterns:",
                *[f"- {item}" for item in lessons.get("fix_patterns", [])],
                f"EvidenceBoundary: {lessons.get('evidence_boundary', '')}",
                "Evidence:",
                *[f"- {item}" for item in evidence],
            ]
        )

        case_id = self.experience_store.persist_case(
            summary=summary,
            root_cause=root_cause,
            trigger_path=trigger_path,
            keywords=keywords,
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

    def get_pageindex_runtime_status(self) -> Dict[str, Any]:
        self.corpus_info = self.experience_store.build_history_corpus()
        self.pageindex_tree.mark_corpus_state(self.corpus_info)
        return self.pageindex_tree.get_runtime_status(self.corpus_info)

    def _retrieve_experiences(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Retrieve historical experiences via tree search, then fallback to lexical retrieval."""
        self.pageindex_tree.sync_history_tree(self.corpus_info)
        status = self.pageindex_tree.get_runtime_status(self.corpus_info)

        if status["tree_cache_ready"]:
            tree_hits = self.pageindex_tree.retrieve_from_tree(query=query, top_k=top_k)
            tree_hits = self._merge_tree_hits_with_records(tree_hits)
            if tree_hits:
                return tree_hits
            self.logger.info("PageIndex tree search returned no hits, falling back to local experience store.")
        else:
            reason = status.get("fallback_reason")
            if reason:
                self.logger.info("PageIndex tree unavailable: %s", reason)

        return self._retrieve_from_local_store(query=query, top_k=top_k)

    def _merge_tree_hits_with_records(self, tree_hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        records = self.experience_store.load_records()
        if not records:
            return tree_hits

        record_map = {str(item.get("case_id", "")): item for item in records}
        merged: List[Dict[str, Any]] = []
        for hit in tree_hits:
            record = record_map.get(str(hit.get("case_id", "")))
            if not record:
                merged.append(hit)
                continue
            lessons = record.get("lessons", {}) or {}
            merged.append(
                {
                    **hit,
                    "summary": record.get("summary", "") or hit.get("summary", ""),
                    "root_cause": record.get("root_cause", ""),
                    "trigger_path": record.get("trigger_path", ""),
                    "case_signature": lessons.get("case_signature", ""),
                    "reusable_playbook": lessons.get("reusable_playbook", []),
                    "applicability": lessons.get("applicability", []),
                    "non_applicability": lessons.get("non_applicability", []),
                }
            )
        return merged

    def _retrieve_from_local_store(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        records = self.experience_store.load_records()
        if not records:
            return []

        query_tokens = set(self._tokenize(query))
        if not query_tokens:
            return []

        scored: List[Dict[str, Any]] = []
        for rec in records:
            text = str(rec.get("retrieval_text", ""))
            tokens = set(self._tokenize(text))
            if not tokens:
                continue

            overlap = len(query_tokens & tokens)
            if overlap == 0:
                continue

            score = overlap / max(len(query_tokens), 1)
            keyword_boost = 0.0
            for kw in rec.get("keywords", []):
                if kw in query_tokens:
                    keyword_boost += 0.05

            scored.append(
                {
                    "case_id": rec.get("case_id"),
                    "summary": rec.get("summary", ""),
                    "root_cause": rec.get("root_cause", ""),
                    "trigger_path": rec.get("trigger_path", ""),
                    "case_signature": rec.get("lessons", {}).get("case_signature", ""),
                    "reusable_playbook": rec.get("lessons", {}).get("reusable_playbook", []),
                    "applicability": rec.get("lessons", {}).get("applicability", []),
                    "non_applicability": rec.get("lessons", {}).get("non_applicability", []),
                    "score": score + keyword_boost,
                    "source": "local_store",
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _summarize_context(
        self,
        crash_report: str,
        profile: Dict[str, Any],
        experience_hits: List[Dict[str, Any]],
        linux_background: List[Dict[str, str]],
    ) -> str:
        experience_text = "\n".join(
            [
                "\n".join(
                    [
                        f"[{idx + 1}] source={item.get('source')} score={item.get('score', 0):.3f}",
                        f"case_id={item.get('case_id', '')}",
                        f"title={item.get('title', '')}",
                        f"summary={item.get('summary', '')}",
                        f"root_cause={item.get('root_cause', '')}",
                        f"trigger_path={item.get('trigger_path', '')}",
                        f"case_signature={item.get('case_signature', '')}",
                        f"playbook={'; '.join(item.get('reusable_playbook', []))}",
                        f"applicability={'; '.join(item.get('applicability', []))}",
                        f"non_applicability={'; '.join(item.get('non_applicability', []))}",
                        f"node_id={item.get('node_id', '')}",
                        f"line_num={item.get('line_num', '')}",
                        f"text={self._shorten(item.get('text', ''), 500)}",
                    ]
                )
                for idx, item in enumerate(experience_hits)
            ]
        ) or "No historical experience retrieved."

        background_text = "\n\n".join(
            [
                f"[{idx + 1}] query={item['query']}\nurl={item['url']}\ncontent={item['content']}"
                for idx, item in enumerate(linux_background)
            ]
        ) or "No extra Linux background was collected."

        summarization_prompt = f"""
You are preparing RAG context for a Linux kernel crash root-cause analysis agent.

Task:
1) Extract similar case signatures from historical experience.
2) Distill a transferable analysis playbook for the current crash.
3) Highlight mismatch signals and non-transferable parts to prevent overfitting.
4) List concrete source-level checks for the next analysis.
5) If evidence is weak, explicitly mark as low-confidence hint.

Crash profile:
{json.dumps(profile, ensure_ascii=False, indent=2)}

Crash report excerpt:
{self._shorten(crash_report, limit=2200)}

Retrieved experiences:
{experience_text}

Linux background:
{background_text}

Output format:
- Section 1: Similar Case Signatures
- Section 2: Transferable Analysis Playbook
- Section 3: Non-Transferable / Mismatch Warnings
- Section 4: Suggested Checks For This Crash
- Section 5: Confidence Notes
""".strip()

        try:
            response = self.summary_agent.invoke(
                {"messages": [HumanMessage(content=summarization_prompt)]},
                config={"recursion_limit": MAX_RECURSION_DEPTH},
            )
            structured = response.get("structured_response") if isinstance(response, dict) else None
            if isinstance(structured, RAGSummaryResult):
                checklist = "\n".join([f"- {item}" for item in structured.analysis_checklist if item.strip()]) or "- none"
                return (
                    "Section 1: Similar Case Signatures\n"
                    f"{structured.historical_experience_insights.strip()}\n\n"
                    "Section 2: Transferable Analysis Playbook\n"
                    f"{structured.linux_module_background.strip()}\n\n"
                    "Section 3: Non-Transferable / Mismatch Warnings\n"
                    "Treat retrieved cases as workflow hints only. Do not reuse old conclusions without current-source proof.\n\n"
                    "Section 4: Suggested Checks For This Crash\n"
                    f"{checklist}\n\n"
                    "Section 5: Confidence Notes\n"
                    f"{structured.confidence_notes.strip()}"
                )
        except Exception as exc:
            self.logger.warning("RAG context summarization failed: %s", exc)

        return (
            "Section 1: Similar Case Signatures\n"
            f"{experience_text}\n\n"
            "Section 2: Transferable Analysis Playbook\n"
            f"{background_text}\n\n"
            "Section 3: Non-Transferable / Mismatch Warnings\n"
            "- Historical experience may only guide check ordering; it is not proof.\n\n"
            "Section 4: Suggested Checks For This Crash\n"
            "- Verify crash-site invalid object first.\n"
            "- Build one-hop taint chain with file/function/line grounding.\n"
            "- Keep fix suggestion minimal and source-grounded.\n\n"
            "Section 5: Confidence Notes\n"
            "- This context is fallback-generated because model summarization failed."
        )

    @staticmethod
    def _create_summary_agent() -> Any:
        system_prompt = """
You are a Linux-kernel RAG summary agent.
Goal: transform retrieved historical cases and Linux background into concise guidance for root-cause analysis.

Rules:
1. Use retrieval as hints, never as final proof.
2. Prioritize case-signature similarity and analysis-playbook transferability.
3. Explicitly call out mismatch signals and non-transferable details.
4. Keep checklist concrete and source-grounded.
5. If retrieval is weak or version-mismatched, call it out explicitly.
""".strip()

        return create_agent(
            model=get_model(),
            tools=[],
            middleware=build_shell_middleware(),
            system_prompt=system_prompt,
            response_format=RAGSummaryResult,
        )

    @staticmethod
    def _create_profile_agent() -> Any:
        system_prompt = """
You extract crash-profile metadata from Linux kernel crash reports.
Return best-effort fields even if report format is irregular.
Do not invent facts; leave unknown fields empty.
""".strip()
        return create_agent(
            model=get_model(),
            tools=[],
            middleware=build_shell_middleware(),
            system_prompt=system_prompt,
            response_format=CrashProfileExtractionResult,
        )

    @staticmethod
    def _create_lessons_agent() -> Any:
        system_prompt = """
You distill one solved kernel crash case into reusable troubleshooting experience.
Output a compact case signature, analysis playbook, applicability boundaries, and fix patterns.
Avoid repeating raw evidence lines verbatim or emitting generic advice.
""".strip()
        return create_agent(
            model=get_model(),
            tools=[],
            middleware=build_shell_middleware(),
            system_prompt=system_prompt,
            response_format=ExperienceLessonsResult,
        )

    def _extract_profile(self, crash_report: str) -> Dict[str, Any]:
        lower = crash_report.lower()
        profile: Dict[str, Any] = {
            "kernel_version": self._extract_kernel_version(crash_report),
            "bug_type": self._extract_bug_type(lower),
            "functions": self._extract_functions(crash_report)[:8],
            "modules": self._extract_modules(crash_report)[:8],
        }

        low_signal = (
            profile["kernel_version"] == "unknown"
            and profile["bug_type"] == "unknown"
            and not profile["functions"]
            and not profile["modules"]
        )
        if low_signal:
            llm_profile = self._extract_profile_with_llm(crash_report)
            profile["kernel_version"] = llm_profile.get("kernel_version") or profile["kernel_version"]
            profile["bug_type"] = llm_profile.get("bug_type") or profile["bug_type"]
            profile["functions"] = llm_profile.get("functions") or profile["functions"]
            profile["modules"] = llm_profile.get("modules") or profile["modules"]

        driver_candidates = list(
            dict.fromkeys(profile["modules"] + self._infer_driver_from_functions(profile["functions"]))
        )
        if not driver_candidates:
            driver_candidates = self._extract_driver_from_source_paths(crash_report)

        keywords = [
            item
            for item in [
                profile["kernel_version"],
                profile["bug_type"],
                *driver_candidates,
                *profile["functions"][:5],
            ]
            if item and item != "unknown"
        ]

        return {
            "kernel_version": profile["kernel_version"],
            "bug_type": profile["bug_type"],
            "functions": profile["functions"][:8],
            "modules": profile["modules"][:8],
            "driver_candidates": driver_candidates[:6],
            "keywords": keywords,
        }

    def _extract_profile_with_llm(self, crash_report: str) -> Dict[str, Any]:
        prompt = f"""
Extract crash profile fields from this kernel crash report.

Report:
{self._shorten(crash_report, limit=5000)}
""".strip()
        try:
            response = self.profile_agent.invoke(
                {"messages": [HumanMessage(content=prompt)]},
                config={"recursion_limit": MAX_RECURSION_DEPTH},
            )
            structured = response.get("structured_response") if isinstance(response, dict) else None
            if isinstance(structured, CrashProfileExtractionResult):
                return structured.model_dump()
        except Exception as exc:
            self.logger.warning("LLM profile extraction failed: %s", exc)
        return {}

    @staticmethod
    def _extract_kernel_version(text: str) -> str:
        patterns = [
            re.compile(r"Linux version\s+([^\s]+)", re.IGNORECASE),
            re.compile(r"kernel version[:\s]+([^\s,]+)", re.IGNORECASE),
            re.compile(r"\b(\d+\.\d+\.\d+[-\w.]*)\b"),
        ]
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return match.group(1)
        return "unknown"

    @staticmethod
    def _extract_bug_type(lower_text: str) -> str:
        candidates = [
            "use-after-free",
            "null pointer dereference",
            "general protection fault",
            "kernel panic",
            "kasan",
            "out-of-bounds",
            "double free",
            "slab-out-of-bounds",
            "page fault",
        ]
        for item in candidates:
            if item in lower_text:
                return item
        return "unknown"

    @staticmethod
    def _extract_functions(text: str) -> List[str]:
        funcs = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]+)\+0x[0-9a-f]+/0x[0-9a-f]+", text)
        return list(dict.fromkeys(funcs))

    @staticmethod
    def _extract_modules(text: str) -> List[str]:
        modules: List[str] = []
        for line in text.splitlines():
            if "Modules linked in:" in line:
                tail = line.split("Modules linked in:", 1)[1]
                for token in tail.split():
                    cleaned = re.sub(r"\(.*?\)", "", token).strip().strip(",")
                    if cleaned and cleaned != "-":
                        modules.append(cleaned)
        return list(dict.fromkeys(modules))

    @staticmethod
    def _infer_driver_from_functions(functions: List[str]) -> List[str]:
        inferred: List[str] = []
        for fn in functions:
            if "_" not in fn:
                continue
            prefix = fn.split("_", 1)[0]
            if len(prefix) >= 3 and prefix not in {"kasan", "__"}:
                inferred.append(prefix)
        return list(dict.fromkeys(inferred))

    def _build_query(self, profile: Dict[str, Any], crash_report: str) -> str:
        query_parts = [
            f"bug_type={profile.get('bug_type', 'unknown')}",
            f"kernel={profile.get('kernel_version', 'unknown')}",
            "drivers=" + ",".join(profile.get("driver_candidates", [])[:3]),
            "functions=" + ",".join(profile.get("functions", [])[:4]),
            "excerpt=" + self._shorten(crash_report.replace("\n", " "), limit=600),
        ]
        return " | ".join(query_parts)

    @staticmethod
    def _extract_driver_from_source_paths(text: str) -> List[str]:
        paths = re.findall(r"(drivers/[a-zA-Z0-9_./-]+)", text)
        candidates: List[str] = []
        for path in paths:
            parts = path.split("/")
            if len(parts) >= 3:
                candidates.append(parts[2])
        return list(dict.fromkeys(candidates))[:6]

    def _summarize_trace(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        tool_calls = trace.get("tool_calls", []) if isinstance(trace, dict) else []
        taint_chain = trace.get("taint_chain", []) if isinstance(trace, dict) else []

        counter = Counter()
        samples: Dict[str, str] = {}
        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            name = str(call.get("name", "")).strip() or "unknown_tool"
            counter[name] += 1
            if name not in samples:
                args_text = self._shorten(json.dumps(call.get("args", {}), ensure_ascii=False), limit=140)
                samples[name] = args_text

        top_tools = [
            {"name": name, "count": count, "sample_args": samples.get(name, "")}
            for name, count in counter.most_common(6)
        ]
        taint_outline = [
            f"{idx + 1}. {item.get('current_function')}::{item.get('variable_name')} "
            f"@ {item.get('file_name')}:{item.get('line')} end={item.get('end')}"
            for idx, item in enumerate(taint_chain[:8])
            if isinstance(item, dict)
        ]
        return {
            "tool_usage": top_tools,
            "tool_total_calls": sum(counter.values()),
            "taint_outline": taint_outline,
            "last_node": trace.get("last_node", "") if isinstance(trace, dict) else "",
        }

    def _distill_experience_lessons(
        self,
        profile: Dict[str, Any],
        analysis_result: Dict[str, Any],
        trace_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        prompt = f"""
Summarize this solved kernel crash case into reusable experience.
Focus on analysis guidance, not prose summary.
Return:
- case_signature
- reusable_playbook
- applicability
- non_applicability
- fix_patterns
- evidence_boundary
- tool_strategy

Profile:
{json.dumps(profile, ensure_ascii=False, indent=2)}

Analysis result:
{json.dumps(analysis_result, ensure_ascii=False, indent=2)}

Trace summary:
{json.dumps(trace_summary, ensure_ascii=False, indent=2)}
""".strip()
        try:
            response = self.lessons_agent.invoke(
                {"messages": [HumanMessage(content=prompt)]},
                config={"recursion_limit": MAX_RECURSION_DEPTH},
            )
            structured = response.get("structured_response") if isinstance(response, dict) else None
            if isinstance(structured, ExperienceLessonsResult):
                return structured.model_dump()
        except Exception as exc:
            self.logger.warning("Experience lesson distillation failed: %s", exc)

        return {
            "case_signature": self._shorten(str(analysis_result.get("trigger_path", "")), limit=240),
            "reusable_playbook": [
                "Anchor the first claim to the exact crash-site object and statement.",
                "Trace one upstream hop at a time until the first credible state boundary.",
                "Separate proven source facts from inferred propagation hypotheses.",
            ],
            "applicability": [
                "The same subsystem, invalid object shape, or source-path family appears in the new crash.",
                "The taint chain includes a similar fetch-from-global, struct field, or lifecycle transition.",
            ],
            "non_applicability": [
                "The crash function matches but the invalid object or access mode is different.",
                "The old case depended on initialization failure while the new case points to a free or race boundary.",
            ],
            "fix_patterns": [
                "Add a guard or invariant check close to the dereference/use site.",
                "Repair the earlier initialization or lifecycle handoff if source evidence proves it.",
            ],
            "evidence_boundary": "Fallback lessons only; no case-specific proof beyond the stored summary.",
            "tool_strategy": "Start from crash report and source line context, then narrow with call/definition queries.",
        }

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return [token.lower() for token in TOKEN_RE.findall(text)]

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        text = str(text or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit] + " ..."

    def _log_pageindex_status(self) -> None:
        status = self.get_pageindex_runtime_status()
        if status["tree_cache_ready"]:
            self.logger.info("PageIndex history tree ready.")
            return
        if status.get("last_sync_status") == "no_history":
            self.logger.info("No historical experience stored yet; skipping history retrieval bootstrap.")
            return
        self.logger.warning("PageIndex history tree unavailable. %s", status.get("fallback_reason", ""))
