import hashlib
import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain.agents import create_agent
from langchain.messages import HumanMessage
from pydantic import BaseModel, Field

from agent_core.model import MAX_RECURSION_DEPTH, get_model
from agent_core.tools.commandTools import build_shell_middleware
from agent_core.tools.WebSearch import fetch_webpage_content, web_search
from log import get_logger

from pageindex import PageIndexClient


TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]+")
URL_RE = re.compile(r"https?://[^\s)]+")


@dataclass
class ExperienceRecord:
    case_id: str
    created_at: str
    summary: str
    root_cause: str
    trigger_path: str
    confidence: str
    keywords: List[str]
    retrieval_text: str
    trace: Dict[str, Any]


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

    def __init__(
        self,
        base_dir: str = "./cache/rag",
        use_pageindex: bool = True,
        pageindex_doc_ids: Optional[List[str]] = None,
    ) -> None:
        """Initialize RAG manager with storage paths, PageIndex client, and helper agents."""
        self.logger = get_logger("analysis_rag")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.experience_jsonl = self.base_dir / "experience_store.jsonl"
        self.experience_docs_dir = self.base_dir / "experience_docs"
        self.experience_docs_dir.mkdir(parents=True, exist_ok=True)

        self.use_pageindex = use_pageindex
        self.pageindex_api_key = os.environ.get("PAGEINDEX_API_KEY")
        raw_doc_ids = os.environ.get("PAGEINDEX_DOC_IDS", "")
        env_doc_ids = [item.strip() for item in raw_doc_ids.split(",") if item.strip()]
        self.pageindex_doc_ids = pageindex_doc_ids if pageindex_doc_ids is not None else env_doc_ids
        self.pageindex_model = os.environ.get("PAGEINDEX_MODEL", "PI-Retrieve")
        self.pageindex_client = self._init_pageindex_client()
        self.summary_agent = self._create_summary_agent()
        self.profile_agent = self._create_profile_agent()
        self.lessons_agent = self._create_lessons_agent()

    def build_pre_analysis_context(self, crash_report: str, top_k: int = 3) -> Dict[str, Any]:
        """Build retrieval context before analyze-agent runs."""
        profile = self._extract_profile(crash_report)
        query = self._build_query(profile, crash_report)

        experience_hits = self._retrieve_experiences(query=query, top_k=top_k)
        linux_background = self._collect_linux_background(profile)
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
        confidence = str(analysis_result.get("confidence", "unknown"))
        fix_suggestion = str(analysis_result.get("fix_suggestion", "")).strip()
        uncertainty = str(analysis_result.get("uncertainty", "") or "").strip()
        crash_site = analysis_result.get("crash_site", {}) or {}
        root_chain = analysis_result.get("root_cause_chain", []) or []
        verification_todo = analysis_result.get("verification_todo", []) or []

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
                f"CrashSite: {crash_site.get('file', 'unknown')}:{crash_site.get('line', 'unknown')} "
                f"{crash_site.get('function', 'unknown')} object={crash_site.get('invalid_object', 'unknown')}",
                f"RootCause: {root_cause}",
                f"TriggerPath: {trigger_path}",
                f"FixSuggestion: {fix_suggestion}",
                f"Uncertainty: {uncertainty}",
                f"CaseSignature: {lessons.get('case_signature', '')}",
                f"ToolStrategy: {lessons.get('tool_strategy', '')}",
                "RootCauseChain:",
                *[
                    f"- step={item.get('step')} {item.get('file')}:{item.get('line')} "
                    f"{item.get('function')}::{item.get('object')} => {item.get('explanation')}"
                    for item in root_chain
                    if isinstance(item, dict)
                ],
                "ReusablePlaybook:",
                *[f"- {item}" for item in lessons.get("reusable_playbook", [])],
                "Applicability:",
                *[f"- {item}" for item in lessons.get("applicability", [])],
                "NonApplicability:",
                *[f"- {item}" for item in lessons.get("non_applicability", [])],
                "FixPatterns:",
                *[f"- {item}" for item in lessons.get("fix_patterns", [])],
                f"EvidenceBoundary: {lessons.get('evidence_boundary', '')}",
                "VerificationTodo:",
                *[f"- {item}" for item in verification_todo if isinstance(item, str) and item.strip()],
                "Evidence:",
                *[f"- {item}" for item in evidence],
            ]
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        case_hash = hashlib.md5((now_iso + retrieval_text).encode("utf-8")).hexdigest()[:12]
        case_id = f"case_{case_hash}"

        record = ExperienceRecord(
            case_id=case_id,
            created_at=now_iso,
            summary=summary,
            root_cause=root_cause,
            trigger_path=trigger_path,
            confidence=confidence,
            keywords=keywords,
            retrieval_text=retrieval_text,
            trace=trace_summary,
        )

        storage_obj = {
            "case_id": record.case_id,
            "created_at": record.created_at,
            "summary": record.summary,
            "root_cause": record.root_cause,
            "trigger_path": record.trigger_path,
            "confidence": record.confidence,
            "keywords": record.keywords,
            "retrieval_text": record.retrieval_text,
            "trace_summary": record.trace,
            "lessons": lessons,
            "profile": profile,
            "analysis_result": analysis_result,
            "retrieved_context": retrieved_context or {},
        }

        with self.experience_jsonl.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(storage_obj, ensure_ascii=False) + "\n")

        md_path = self.experience_docs_dir / f"{case_id}.md"
        md_content = self._to_markdown(storage_obj)
        md_path.write_text(md_content, encoding="utf-8")

        self.logger.info("Persisted successful analysis case: %s", case_id)
        return case_id

    def _retrieve_experiences(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Retrieve historical experiences, preferring PageIndex when configured."""
        if self.use_pageindex and self.pageindex_api_key and self.pageindex_doc_ids:
            hits = self._retrieve_from_pageindex(query=query, top_k=top_k)
            if hits:
                return hits

        return self._retrieve_from_local_store(query=query, top_k=top_k)

    def _retrieve_from_local_store(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Fallback lexical retrieval from local jsonl experience store."""
        records = self._load_records()
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
                    "confidence": rec.get("confidence", "unknown"),
                    "score": score + keyword_boost,
                    "source": "local_store",
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _retrieve_from_pageindex(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Retrieve relevant experience snippets through PageIndex Python SDK."""
        if self.pageindex_client is None:
            return []

        try:
            response = self.pageindex_client.chat_completions(
                model=self.pageindex_model,
                doc_id=self.pageindex_doc_ids,
                messages=[
                    {
                        "role": "system",
                        "content": "Return concise, case-level kernel crash experiences useful for root-cause analysis.",
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Find up to {top_k} relevant historical experiences for this query.\n"
                            "Prioritize root-cause and trigger-path similarity.\n"
                            f"Query:\n{query}"
                        ),
                    },
                ],
                stream=False,
            )
        except Exception as exc:
            self.logger.warning("PageIndex SDK retrieval exception: %s", exc)
            return []

        content = self._extract_pageindex_content(response)

        if not content:
            return []

        return [
            {
                "case_id": "pageindex",
                "summary": self._shorten(content, limit=1200),
                "root_cause": "",
                "trigger_path": "",
                "case_signature": "",
                "reusable_playbook": [],
                "applicability": [],
                "non_applicability": [],
                "confidence": "reference",
                "score": 1.0,
                "source": "pageindex",
            }
        ]

    def _collect_linux_background(self, profile: Dict[str, Any]) -> List[Dict[str, str]]:
        """Collect Linux module/subsystem technical context from high-quality domains."""
        if "TAVILY_API_KEY" not in os.environ:
            return []

        queries = self._build_linux_queries(profile)
        if not queries:
            return []

        backgrounds: List[Dict[str, str]] = []
        for query in queries[:2]:
            try:
                result_text = web_search.func(
                    query=query,
                    max_results=3,
                    search_depth="advanced",
                    include_domains=["docs.kernel.org", "lore.kernel.org", "kernel.org", "syzkaller.appspot.com"],
                )
            except Exception as exc:
                self.logger.warning("web_search failed: %s", exc)
                continue

            if not isinstance(result_text, str) or result_text.startswith("Error:"):
                continue

            urls = URL_RE.findall(result_text)
            for url in urls[:2]:
                try:
                    page = fetch_webpage_content.func(url=url, max_length=2200)
                except Exception:
                    continue
                if not isinstance(page, str) or page.startswith("Error:"):
                    continue
                backgrounds.append(
                    {
                        "query": query,
                        "url": url,
                        "content": self._shorten(page, limit=1600),
                    }
                )
                if len(backgrounds) >= 3:
                    return backgrounds

        return backgrounds

    def _summarize_context(
        self,
        crash_report: str,
        profile: Dict[str, Any],
        experience_hits: List[Dict[str, Any]],
        linux_background: List[Dict[str, str]],
    ) -> str:
        """Summarize retrieved evidence into compact context for analyze agent."""
        experience_text = "\n".join(
            [
                f"[{idx + 1}] source={item.get('source')} score={item.get('score', 0):.3f}\n"
                f"summary={item.get('summary', '')}\n"
                f"root_cause={item.get('root_cause', '')}\n"
                f"trigger_path={item.get('trigger_path', '')}\n"
                f"case_signature={item.get('case_signature', '')}\n"
                f"playbook={'; '.join(item.get('reusable_playbook', []))}\n"
                f"applicability={'; '.join(item.get('applicability', []))}\n"
                f"non_applicability={'; '.join(item.get('non_applicability', []))}"
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
                checklist = "\n".join([f"- {item}" for item in structured.analysis_checklist if item.strip()])
                checklist = checklist or "- none"
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

    def _init_pageindex_client(self) -> Any:
        """Create the PageIndex SDK client used for vectorless retrieval."""
        if not self.use_pageindex:
            return None
        if not self.pageindex_api_key:
            return None

        try:
            return PageIndexClient(api_key=self.pageindex_api_key)
        except Exception as exc:
            self.logger.warning("Failed to initialize PageIndexClient: %s", exc)
            return None

    @staticmethod
    def _extract_pageindex_content(response: Any) -> str:
        """Normalize PageIndex SDK response to plain text content."""
        if response is None:
            return ""

        if isinstance(response, dict):
            choices = response.get("choices", [])
            if choices:
                msg = choices[0].get("message", {})
                return str(msg.get("content", "")).strip()
            return str(response).strip()

        choices = getattr(response, "choices", None)
        if isinstance(choices, list) and choices:
            first = choices[0]
            message = getattr(first, "message", None)
            content = getattr(message, "content", "") if message is not None else ""
            return str(content).strip()

        return str(response).strip()

    @staticmethod
    def _create_summary_agent() -> Any:
        """Create a dedicated agent that transforms retrieval outputs into RAG briefing."""
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
        """Create an agent to robustly extract crash profile when regex heuristics are weak."""
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
        """Create an agent to distill solved-case outputs into reusable analysis experience."""
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
        """Extract crash profile with regex-first strategy and LLM fallback for format drift."""
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
        """Fallback crash-profile extraction for non-standard crash report formats."""
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
                    cleaned = re.sub(r"\(.*?\)", "", token).strip()
                    cleaned = cleaned.strip(",")
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

    def _build_linux_queries(self, profile: Dict[str, Any]) -> List[str]:
        """Build module-technology-oriented queries instead of vulnerability-oriented queries."""
        kernel_version = profile.get("kernel_version", "unknown")
        drivers = profile.get("driver_candidates", [])
        functions = profile.get("functions", [])

        queries: List[str] = []
        if drivers:
            queries.append(f"Linux kernel {drivers[0]} driver architecture and data path")
            queries.append(f"docs.kernel.org {drivers[0]} driver design")
        if functions:
            queries.append(f"Linux kernel function {functions[0]} responsibilities and call chain")
        if kernel_version != "unknown":
            queries.append(f"Linux kernel {kernel_version} subsystem documentation and behavior changes")
        queries.append("Linux kernel driver debugging workflow docs.kernel.org")

        return list(dict.fromkeys(queries))

    @staticmethod
    def _extract_driver_from_source_paths(text: str) -> List[str]:
        """Extract probable driver/module names from source paths in crash report text."""
        paths = re.findall(r"(drivers/[a-zA-Z0-9_./-]+)", text)
        candidates: List[str] = []
        for path in paths:
            parts = path.split("/")
            if len(parts) >= 3:
                candidates.append(parts[2])
        return list(dict.fromkeys(candidates))[:6]

    def _load_records(self) -> List[Dict[str, Any]]:
        """Load persisted experience records from jsonl store."""
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
                    continue
        return records

    def _summarize_trace(self, trace: Dict[str, Any]) -> Dict[str, Any]:
        """Compress verbose runtime trace into concise, retrieval-friendly summaries."""
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
        """Convert one solved case into reusable lessons instead of raw record dumping."""
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
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[:limit] + " ..."

    def _to_markdown(self, storage_obj: Dict[str, Any]) -> str:
        """Render one stored experience into readable markdown card."""
        analysis_result = storage_obj.get("analysis_result", {})
        profile = storage_obj.get("profile", {})
        trace = storage_obj.get("trace_summary", {})
        lessons = storage_obj.get("lessons", {})

        evidence = analysis_result.get("evidence", [])
        evidence_text = "\n".join([f"- {item}" for item in evidence]) if evidence else "- none"

        tool_usage = trace.get("tool_usage", [])
        tool_lines = "\n".join(
            [
                f"- {item.get('name')} x{item.get('count')} (sample args: {item.get('sample_args')})"
                for item in tool_usage
            ]
        )
        if not tool_lines:
            tool_lines = "- none"

        taint_outline = trace.get("taint_outline", [])
        taint_lines = "\n".join([f"- {item}" for item in taint_outline])
        if not taint_lines:
            taint_lines = "- none"
        playbook_text = "\n".join([f"- {item}" for item in lessons.get("reusable_playbook", [])]) or "- none"
        applicability_text = "\n".join([f"- {item}" for item in lessons.get("applicability", [])]) or "- none"
        non_applicability_text = "\n".join([f"- {item}" for item in lessons.get("non_applicability", [])]) or "- none"
        fix_patterns_text = "\n".join([f"- {item}" for item in lessons.get("fix_patterns", [])]) or "- none"
        verification_todo = analysis_result.get("verification_todo", [])
        verification_todo_text = "\n".join([f"- {item}" for item in verification_todo]) or "- none"
        patch_sketch = analysis_result.get("patch_sketch", "") or "none"
        crash_site = analysis_result.get("crash_site", {}) or {}
        crash_site_text = (
            f"- file: {crash_site.get('file', 'unknown')}\n"
            f"- function: {crash_site.get('function', 'unknown')}\n"
            f"- line: {crash_site.get('line', 'unknown')}\n"
            f"- invalid_object: {crash_site.get('invalid_object', 'unknown')}\n"
            f"- statement: {crash_site.get('statement', 'unknown')}"
        )

        return (
            f"# {storage_obj.get('case_id')}\n\n"
            f"- created_at: {storage_obj.get('created_at')}\n"
            f"- confidence: {analysis_result.get('confidence', 'unknown')}\n"
            f"- kernel_version: {profile.get('kernel_version', 'unknown')}\n"
            f"- bug_type: {profile.get('bug_type', 'unknown')}\n"
            f"- driver_candidates: {', '.join(profile.get('driver_candidates', [])) or 'none'}\n\n"
            "## Root Cause\n"
            f"{analysis_result.get('root_cause', '')}\n\n"
            "## Crash Site\n"
            f"{crash_site_text}\n\n"
            "## Trigger Path\n"
            f"{analysis_result.get('trigger_path', '')}\n\n"
            "## Case Signature\n"
            f"{lessons.get('case_signature', '')}\n\n"
            "## Evidence\n"
            f"{evidence_text}\n\n"
            "## Fix Suggestion\n"
            f"{analysis_result.get('fix_suggestion', '')}\n\n"
            "## Reusable Playbook\n"
            f"{playbook_text}\n\n"
            "## Applicability\n"
            f"{applicability_text}\n\n"
            "## Non-Applicability\n"
            f"{non_applicability_text}\n\n"
            "## Fix Patterns\n"
            f"{fix_patterns_text}\n\n"
            "## Evidence Boundary\n"
            f"{lessons.get('evidence_boundary', '')}\n\n"
            "## Tool Strategy\n"
            f"{lessons.get('tool_strategy', '')}\n\n"
            "## Verification TODO\n"
            f"{verification_todo_text}\n\n"
            "## Patch Sketch\n"
            f"```diff\n{patch_sketch}\n```\n\n"
            "## Taint Chain\n"
            f"{taint_lines}\n\n"
            "## Tool Calls\n"
            f"{tool_lines}\n"
        )
