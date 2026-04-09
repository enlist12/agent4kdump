import hashlib
import json
import os
import re
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

try:
    from pageindex import PageIndexClient
except Exception:  # pragma: no cover - optional dependency in runtime env
    PageIndexClient = None


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


class AnalysisRAGManager:
    """Build pre-analysis RAG context and persist successful analysis experience."""

    def __init__(
        self,
        base_dir: str = "./cache/rag",
        use_pageindex: bool = True,
        pageindex_doc_ids: Optional[List[str]] = None,
    ) -> None:
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

    def build_pre_analysis_context(self, crash_report: str, top_k: int = 3) -> Dict[str, Any]:
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
        profile = self._extract_profile(crash_report)
        root_cause = str(analysis_result.get("root_cause", "")).strip()
        trigger_path = str(analysis_result.get("trigger_path", "")).strip()
        evidence = analysis_result.get("evidence", [])
        confidence = str(analysis_result.get("confidence", "unknown"))
        fix_suggestion = str(analysis_result.get("fix_suggestion", "")).strip()
        uncertainty = str(analysis_result.get("uncertainty", "") or "").strip()

        summary = self._shorten(" ".join([root_cause, trigger_path, fix_suggestion]), limit=280)
        keywords = profile.get("keywords", [])

        retrieval_text = "\n".join(
            [
                f"BugType: {profile.get('bug_type', 'unknown')}",
                f"KernelVersion: {profile.get('kernel_version', 'unknown')}",
                f"DriverCandidates: {', '.join(profile.get('driver_candidates', [])) or 'none'}",
                f"Functions: {', '.join(profile.get('functions', [])) or 'none'}",
                f"RootCause: {root_cause}",
                f"TriggerPath: {trigger_path}",
                f"FixSuggestion: {fix_suggestion}",
                f"Uncertainty: {uncertainty}",
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
            trace=trace or {},
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
            "trace": record.trace,
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
        if self.use_pageindex and self.pageindex_api_key and self.pageindex_doc_ids:
            hits = self._retrieve_from_pageindex(query=query, top_k=top_k)
            if hits:
                return hits

        return self._retrieve_from_local_store(query=query, top_k=top_k)

    def _retrieve_from_local_store(self, query: str, top_k: int) -> List[Dict[str, Any]]:
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
                    "confidence": rec.get("confidence", "unknown"),
                    "score": score + keyword_boost,
                    "source": "local_store",
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored[:top_k]

    def _retrieve_from_pageindex(self, query: str, top_k: int) -> List[Dict[str, Any]]:
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
                "confidence": "reference",
                "score": 1.0,
                "source": "pageindex",
            }
        ]

    def _collect_linux_background(self, profile: Dict[str, Any]) -> List[Dict[str, str]]:
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
        experience_text = "\n".join(
            [
                f"[{idx + 1}] source={item.get('source')} score={item.get('score', 0):.3f}\n"
                f"summary={item.get('summary', '')}\n"
                f"root_cause={item.get('root_cause', '')}\n"
                f"trigger_path={item.get('trigger_path', '')}"
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
1) Summarize actionable historical experience patterns.
2) Summarize kernel/module background linked to this crash.
3) List concrete pitfalls/checkpoints for the next analysis.
4) If evidence is weak, explicitly mark as low-confidence hint.

Crash profile:
{json.dumps(profile, ensure_ascii=False, indent=2)}

Crash report excerpt:
{self._shorten(crash_report, limit=2200)}

Retrieved experiences:
{experience_text}

Linux background:
{background_text}

Output format:
- Section 1: Historical Experience Insights
- Section 2: Linux Module Background
- Section 3: Analysis Checklist
- Section 4: Confidence Notes
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
                    "Section 1: Historical Experience Insights\n"
                    f"{structured.historical_experience_insights.strip()}\n\n"
                    "Section 2: Linux Module Background\n"
                    f"{structured.linux_module_background.strip()}\n\n"
                    "Section 3: Analysis Checklist\n"
                    f"{checklist}\n\n"
                    "Section 4: Confidence Notes\n"
                    f"{structured.confidence_notes.strip()}"
                )
        except Exception as exc:
            self.logger.warning("RAG context summarization failed: %s", exc)

        return (
            "Section 1: Historical Experience Insights\n"
            f"{experience_text}\n\n"
            "Section 2: Linux Module Background\n"
            f"{background_text}\n\n"
            "Section 3: Analysis Checklist\n"
            "- Verify crash-site invalid object first.\n"
            "- Build one-hop taint chain with file/function/line grounding.\n"
            "- Keep fix suggestion minimal and source-grounded.\n\n"
            "Section 4: Confidence Notes\n"
            "- This context is fallback-generated because model summarization failed."
        )

    def _init_pageindex_client(self) -> Any:
        if not self.use_pageindex:
            return None
        if PageIndexClient is None:
            self.logger.warning("PageIndex SDK is not installed. Falling back to local store retrieval.")
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
        system_prompt = """
You are a Linux-kernel RAG summary agent.
Goal: transform retrieved historical cases and Linux background into concise guidance for root-cause analysis.

Rules:
1. Use retrieval as hints, never as final proof.
2. Prioritize root-cause and trigger-path transferability.
3. Keep checklist concrete and source-grounded.
4. If retrieval is weak or version-mismatched, call it out explicitly.
""".strip()

        return create_agent(
            model=get_model(),
            tools=[],
            middleware=build_shell_middleware(),
            system_prompt=system_prompt,
            response_format=RAGSummaryResult,
        )

    def _extract_profile(self, crash_report: str) -> Dict[str, Any]:
        lower = crash_report.lower()
        kernel_version = self._extract_kernel_version(crash_report)
        bug_type = self._extract_bug_type(lower)
        functions = self._extract_functions(crash_report)
        modules = self._extract_modules(crash_report)

        driver_candidates = list(dict.fromkeys(modules + self._infer_driver_from_functions(functions)))
        keywords = [item for item in [kernel_version, bug_type, *driver_candidates, *functions[:5]] if item]

        return {
            "kernel_version": kernel_version,
            "bug_type": bug_type,
            "functions": functions[:8],
            "modules": modules[:8],
            "driver_candidates": driver_candidates[:6],
            "keywords": keywords,
        }

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
        bug_type = profile.get("bug_type", "unknown")
        kernel_version = profile.get("kernel_version", "unknown")
        drivers = profile.get("driver_candidates", [])
        functions = profile.get("functions", [])

        queries: List[str] = []
        if drivers:
            queries.append(f"Linux kernel {drivers[0]} driver {bug_type} {kernel_version}")
        if functions:
            queries.append(f"Linux kernel function {functions[0]} crash analysis {bug_type}")
        queries.append(f"Linux kernel {bug_type} debugging checklist {kernel_version}")

        return list(dict.fromkeys([q for q in queries if "unknown" not in q.lower()]))

    def _load_records(self) -> List[Dict[str, Any]]:
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
        analysis_result = storage_obj.get("analysis_result", {})
        profile = storage_obj.get("profile", {})
        trace = storage_obj.get("trace", {})

        evidence = analysis_result.get("evidence", [])
        evidence_text = "\n".join([f"- {item}" for item in evidence]) if evidence else "- none"

        tool_calls = trace.get("tool_calls", [])
        tool_lines = "\n".join([f"- {item.get('name')}: {item.get('args')}" for item in tool_calls])
        if not tool_lines:
            tool_lines = "- none"

        taint_chain = trace.get("taint_chain", [])
        taint_lines = "\n".join(
            [
                f"- {idx + 1}. {item.get('file_name')}:{item.get('line')} {item.get('variable_name')} "
                f"({item.get('current_function')}) end={item.get('end')}"
                for idx, item in enumerate(taint_chain)
            ]
        )
        if not taint_lines:
            taint_lines = "- none"

        return (
            f"# {storage_obj.get('case_id')}\n\n"
            f"- created_at: {storage_obj.get('created_at')}\n"
            f"- confidence: {analysis_result.get('confidence', 'unknown')}\n"
            f"- kernel_version: {profile.get('kernel_version', 'unknown')}\n"
            f"- bug_type: {profile.get('bug_type', 'unknown')}\n"
            f"- driver_candidates: {', '.join(profile.get('driver_candidates', [])) or 'none'}\n\n"
            "## Root Cause\n"
            f"{analysis_result.get('root_cause', '')}\n\n"
            "## Trigger Path\n"
            f"{analysis_result.get('trigger_path', '')}\n\n"
            "## Evidence\n"
            f"{evidence_text}\n\n"
            "## Fix Suggestion\n"
            f"{analysis_result.get('fix_suggestion', '')}\n\n"
            "## Taint Chain\n"
            f"{taint_lines}\n\n"
            "## Tool Calls\n"
            f"{tool_lines}\n"
        )
