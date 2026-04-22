import hashlib
import json
import os
import re
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from langchain.agents import create_agent
from langchain.messages import HumanMessage
from pydantic import AliasChoices
from pydantic import BaseModel, Field
from pageindex.page_index_md import md_to_tree
from pageindex.utils import ConfigLoader

from agent_core.model import MAX_RECURSION_DEPTH, get_model
from agent_core.tools.commandTools import build_shell_middleware


TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]+")
CASE_ID_RE = re.compile(r"\bcase_[0-9a-f]{12}\b")


class TreeSearchResult(BaseModel):
    selected_node_ids: List[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("selected_node_ids", "node_list"),
    )
    reasoning: str = Field(
        default="",
        validation_alias=AliasChoices("reasoning", "thinking"),
    )


class PageIndexTreeRetriever:
    """Maintain PageIndex markdown tree cache and retrieve relevant tree nodes."""

    def __init__(self, base_dir: Path, logger: Any, enabled: bool = True) -> None:
        self.base_dir = Path(base_dir)
        self.logger = logger
        self.enabled = enabled
        self.pageindex_api_key = os.environ.get("PAGEINDEX_API_KEY", "").strip()
        self._bridge_pageindex_llm_env()
        self.tree_cache_path = self.base_dir / "pageindex_tree.json"
        self.state_cache_path = self.base_dir / "pageindex_state.json"
        self._current_corpus_info: Dict[str, Any] = {
            "exists": False,
            "record_count": 0,
            "corpus_hash": "",
            "corpus_path": self.base_dir / "history_corpus.md",
        }
        self._pageindex_opt = ConfigLoader().load({})
        self.tree_search_agent = self._create_tree_search_agent()
        self._ensure_state_file()

    def _bridge_pageindex_llm_env(self) -> None:
        """Map the project's LLM env vars to the OpenAI-style vars expected by PageIndex/litellm."""
        if not os.environ.get("OPENAI_API_KEY"):
            fallback_key = os.environ.get("API_KEY") or os.environ.get("CHATGPT_API_KEY")
            if fallback_key:
                os.environ["OPENAI_API_KEY"] = fallback_key

        if not os.environ.get("OPENAI_API_BASE"):
            fallback_base = os.environ.get("LLM_BASE_URL")
            if fallback_base:
                os.environ["OPENAI_API_BASE"] = fallback_base

    def mark_corpus_state(self, corpus_info: Dict[str, Any]) -> None:
        """Refresh state metadata after corpus changes without forcing remote sync."""
        self._current_corpus_info = dict(corpus_info)
        state = self._load_state()
        current_hash = corpus_info.get("corpus_hash", "")
        tree_hash = state.get("corpus_hash", "")
        tree_exists = self.tree_cache_path.exists()
        has_history = bool(corpus_info.get("exists"))

        if not has_history:
            if tree_exists:
                self.tree_cache_path.unlink()
            state.update(
                {
                    "corpus_hash": "",
                    "current_corpus_hash": "",
                    "tree_cache_stale": False,
                    "last_sync_status": "no_history",
                    "last_error": "",
                }
            )
            self._save_state(state)
            return

        tree_stale = not tree_exists or tree_hash != current_hash
        state["current_corpus_hash"] = current_hash
        state["tree_cache_stale"] = tree_stale
        if not tree_stale and state.get("last_sync_status") in {
            "",
            "backend_missing",
            "local_backend_failed",
            "sync_failed",
        }:
            state["last_sync_status"] = "cache_ready"
            state["last_error"] = ""
        self._save_state(state)

    def sync_history_tree(self, corpus_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Synchronize local PageIndex tree cache against current markdown corpus."""
        if corpus_info is not None:
            self._current_corpus_info = dict(corpus_info)
        corpus_info = self._current_corpus_info
        state = self._load_state()

        if not self.enabled:
            state["last_sync_status"] = "disabled"
            state["last_error"] = "PageIndex disabled by configuration."
            self._save_state(state)
            return state

        if not corpus_info.get("exists"):
            state.update(
                {
                    "corpus_hash": "",
                    "current_corpus_hash": "",
                    "tree_cache_stale": False,
                    "last_sync_status": "no_history",
                    "last_error": "",
                }
            )
            self._save_state(state)
            return state

        current_hash = str(corpus_info.get("corpus_hash", ""))
        tree_exists = self.tree_cache_path.exists()
        tree_hash = str(state.get("corpus_hash", ""))

        state["current_corpus_hash"] = current_hash
        if tree_exists and tree_hash == current_hash:
            state["tree_cache_stale"] = False
            state["last_sync_status"] = "cache_ready"
            state["last_error"] = ""
            self._save_state(state)
            return state

        corpus_path = Path(corpus_info["corpus_path"])
        try:
            raw_tree = asyncio.run(
                md_to_tree(
                    md_path=str(corpus_path),
                    if_thinning=False,
                    min_token_threshold=5000,
                    if_add_node_summary=self._pageindex_opt.if_add_node_summary,
                    summary_token_threshold=200,
                    model=self._pageindex_opt.model,
                    if_add_doc_description=self._pageindex_opt.if_add_doc_description,
                    if_add_node_text=self._pageindex_opt.if_add_node_text,
                    if_add_node_id=self._pageindex_opt.if_add_node_id,
                )
            )
        except Exception as exc:
            state["tree_cache_stale"] = True
            state["last_sync_status"] = "local_backend_failed"
            state["last_error"] = f"PageIndex markdown tree generation failed: {exc}"
            self._save_state(state)
            self.logger.warning("PageIndex markdown tree generation failed: %s", exc)
            return state

        self.tree_cache_path.write_text(json.dumps(raw_tree, ensure_ascii=False, indent=2), encoding="utf-8")
        state.update(
            {
                "corpus_hash": current_hash,
                "current_corpus_hash": current_hash,
                "tree_cache_stale": False,
                "last_sync_status": "synced",
                "last_error": "",
                "last_synced_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._save_state(state)
        return state

    def retrieve_from_tree(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        """Retrieve relevant tree nodes with local LLM-guided tree search."""
        if not self.tree_cache_path.exists():
            return []

        try:
            raw_tree = json.loads(self.tree_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning("Failed to read tree cache: %s", exc)
            return []

        normalized = self._normalize_tree(raw_tree)
        if not normalized["nodes"]:
            self.logger.info(
                "PageIndex tree normalization produced no nodes. top_level_keys=%s",
                list(raw_tree.keys()) if isinstance(raw_tree, dict) else type(raw_tree).__name__,
            )
            return []

        self.logger.info(
            "PageIndex tree loaded for retrieval. roots=%d nodes=%d query=%s",
            len(normalized["root_ids"]),
            len(normalized["nodes"]),
            self._shorten(query, 240),
        )
        self.logger.info(
            "PageIndex tree root preview: %s",
            json.dumps(
                [
                    {
                        "node_id": normalized["nodes"][node_id]["node_id"],
                        "title": normalized["nodes"][node_id].get("title", ""),
                    }
                    for node_id in normalized["root_ids"][:8]
                    if node_id in normalized["nodes"]
                ],
                ensure_ascii=False,
            ),
        )

        selected_ids = self._run_tree_search(query=query, normalized=normalized, top_k=top_k)
        if not selected_ids:
            ranked = self._rank_nodes_by_overlap(query=query, normalized=normalized, limit=min(8, len(normalized["nodes"])))
            self.logger.info(
                "PageIndex tree search selected no nodes. Top overlap candidates: %s",
                json.dumps(
                    [
                        {
                            "node_id": node["node_id"],
                            "title": node.get("title", ""),
                            "score": round(score, 4),
                            "summary": self._shorten(node.get("summary", ""), 120),
                        }
                        for score, node in ranked
                    ],
                    ensure_ascii=False,
                ),
            )
            return []
        self.logger.info("PageIndex tree search selected node ids: %s", selected_ids)
        return self._nodes_to_hits(query=query, selected_ids=selected_ids, normalized=normalized, top_k=top_k)

    def get_runtime_status(self, corpus_info: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if corpus_info is not None:
            self._current_corpus_info = dict(corpus_info)

        state = self._load_state()
        current_hash = str(self._current_corpus_info.get("corpus_hash", "")) or str(
            state.get("current_corpus_hash", "")
        )
        has_history = bool(self._current_corpus_info.get("exists"))
        tree_exists = self.tree_cache_path.exists()
        tree_cache_stale = bool(has_history and (not tree_exists or state.get("corpus_hash", "") != current_hash))
        tree_cache_ready = bool(has_history and tree_exists and not tree_cache_stale)

        fallback_reason = ""
        if not self.enabled:
            fallback_reason = "PageIndex disabled by configuration."
        elif has_history and state.get("last_error") and not tree_cache_ready:
            fallback_reason = str(state.get("last_error"))
        elif has_history and not tree_cache_ready:
            fallback_reason = "History tree is not ready; falling back to local experience retrieval."

        return {
            "enabled": self.enabled,
            "api_key_configured": bool(self.pageindex_api_key),
            "markdown_backend_ready": True,
            "tree_cache_ready": tree_cache_ready,
            "tree_cache_stale": tree_cache_stale,
            "last_sync_status": state.get("last_sync_status", ""),
            "fallback_reason": fallback_reason,
        }

    @staticmethod
    def _create_tree_search_agent() -> Any:
        system_prompt = """
You are selecting relevant nodes from a markdown tree built from historical kernel crash cases.
Return only node ids that are useful for the current crash query.
Prefer branch nodes that lead to the right case and leaf nodes that contain root cause, trigger path,
playbook, applicability, or fix-pattern details.
Do not invent node ids.
""".strip()
        return create_agent(
            model=get_model(),
            tools=[],
            middleware=build_shell_middleware(),
            system_prompt=system_prompt,
            response_format=TreeSearchResult,
        )

    def _run_tree_search(self, query: str, normalized: Dict[str, Any], top_k: int) -> List[str]:
        selected_ids = self._llm_select_node_ids_from_tree(query=query, normalized=normalized, limit=max(top_k, 3))
        if selected_ids:
            ranked_selected = sorted(
                selected_ids,
                key=lambda node_id: self._overlap_score(query, normalized["nodes"].get(node_id, {})),
                reverse=True,
            )
            return ranked_selected[:top_k]

        ranked = self._rank_nodes_by_overlap(query=query, normalized=normalized, limit=max(top_k, 3))
        return [node["node_id"] for score, node in ranked if score > 0][:top_k]

    def _llm_select_node_ids_from_tree(self, query: str, normalized: Dict[str, Any], limit: int) -> List[str]:
        tree_without_text = self._build_tree_without_text(normalized=normalized)
        if not tree_without_text:
            return []

        prompt = f"""
You are given a question and a tree structure of a document.
Each node contains a node id, node title, line number, and a corresponding summary.
Your task is to find all nodes that are likely to contain the answer to the question.

Query:
{query}

Document tree structure:
{json.dumps(tree_without_text, ensure_ascii=False, indent=2)}

Please reply in the following JSON format:
{{
  "thinking": "",
  "node_list": ["node_id_1", "node_id_2"]
}}

Directly return the final JSON structure. Do not output anything else.
""".strip()
        self.logger.info("PageIndex tree search prompt prepared. tree_nodes=%d", len(normalized["nodes"]))
        try:
            response = self.tree_search_agent.invoke(
                {"messages": [HumanMessage(content=prompt)]},
                config={"recursion_limit": MAX_RECURSION_DEPTH},
            )
            structured = response.get("structured_response") if isinstance(response, dict) else None
            if isinstance(structured, TreeSearchResult):
                self.logger.info("PageIndex tree search reasoning: %s", self._shorten(structured.reasoning, 400))
                return [
                    node_id
                    for node_id in structured.selected_node_ids
                    if node_id in normalized["nodes"]
                ][:limit]
        except Exception as exc:
            self.logger.warning("Tree search selection failed: %s", exc)
        return []

    def _build_tree_without_text(self, normalized: Dict[str, Any]) -> List[Dict[str, Any]]:
        def build_node(node_id: str) -> Dict[str, Any]:
            node = normalized["nodes"][node_id]
            result = {
                "title": node.get("title", ""),
                "node_id": node["node_id"],
                "line_num": node.get("line_num"),
            }
            summary = node.get("summary", "") or node.get("prefix_summary", "")
            if summary:
                if node.get("children"):
                    result["prefix_summary"] = summary
                else:
                    result["summary"] = summary
            if node.get("children"):
                result["nodes"] = [build_node(child_id) for child_id in node["children"] if child_id in normalized["nodes"]]
            return result

        return [build_node(node_id) for node_id in normalized["root_ids"] if node_id in normalized["nodes"]]

    def _rank_nodes_by_overlap(
        self,
        *,
        query: str,
        normalized: Dict[str, Any],
        limit: int,
    ) -> List[tuple[float, Dict[str, Any]]]:
        ranked = sorted(
            [
                (self._overlap_score(query, node), node)
                for node in normalized["nodes"].values()
            ],
            key=lambda item: item[0],
            reverse=True,
        )
        return ranked[:limit]

    def _nodes_to_hits(
        self,
        *,
        query: str,
        selected_ids: List[str],
        normalized: Dict[str, Any],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        hits: List[Dict[str, Any]] = []
        for rank, node_id in enumerate(selected_ids[:top_k], start=1):
            node = normalized["nodes"].get(node_id)
            if not node:
                continue
            text = node.get("text", "")
            summary = node.get("summary", "") or node.get("prefix_summary", "") or node.get("title", "")
            case_id = self._extract_case_id(node_id=node_id, normalized=normalized)
            hits.append(
                {
                    "case_id": case_id,
                    "summary": self._shorten(summary or text, 500),
                    "root_cause": "",
                    "trigger_path": "",
                    "case_signature": "",
                    "reusable_playbook": [],
                    "applicability": [],
                    "non_applicability": [],
                    "confidence": "reference",
                    "score": max(1.0 - (rank - 1) * 0.1, 0.1) + self._overlap_score(query, node),
                    "source": "pageindex_tree",
                    "node_id": node_id,
                    "title": node.get("title", ""),
                    "text": self._shorten(text, 800),
                    "line_num": node.get("line_num"),
                }
            )
        return hits

    def _extract_case_id(self, node_id: str, normalized: Dict[str, Any]) -> str:
        current_id = node_id
        while current_id:
            node = normalized["nodes"].get(current_id) or {}
            for candidate in [
                node.get("title", ""),
                node.get("summary", ""),
                node.get("prefix_summary", ""),
                node.get("text", ""),
            ]:
                match = CASE_ID_RE.search(str(candidate))
                if match:
                    return match.group(0)
            current_id = node.get("parent_id")
        return ""

    def _normalize_tree(self, raw_tree: Any) -> Dict[str, Any]:
        nodes: Dict[str, Dict[str, Any]] = {}
        roots: List[str] = []

        def register(node: Dict[str, Any], parent_id: Optional[str]) -> str:
            raw_id = node.get("node_id") or node.get("id") or node.get("uuid") or node.get("key")
            if raw_id is None:
                raw_id = hashlib.md5(
                    json.dumps(node, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()[:12]
            node_id = str(raw_id)

            if node_id not in nodes:
                nodes[node_id] = {
                    "node_id": node_id,
                    "title": self._extract_text_field(node, ["title", "name", "heading", "label"]),
                    "summary": self._extract_text_field(node, ["summary", "abstract", "description"]),
                    "prefix_summary": self._extract_text_field(node, ["prefix_summary"]),
                    "text": self._extract_text_field(node, ["text", "content", "body", "markdown", "value"]),
                    "line_num": node.get("line_num")
                    or node.get("line")
                    or (node.get("metadata", {}) or {}).get("line_num")
                    or (node.get("metadata", {}) or {}).get("line"),
                    "children": [],
                    "parent_id": parent_id,
                }
            else:
                if parent_id and not nodes[node_id].get("parent_id"):
                    nodes[node_id]["parent_id"] = parent_id

            if parent_id is None and node_id not in roots:
                roots.append(node_id)

            children = node.get("children") or node.get("nodes") or node.get("sections") or []
            for child in children if isinstance(children, list) else []:
                if isinstance(child, dict):
                    child_id = register(child, parent_id=node_id)
                    if child_id not in nodes[node_id]["children"]:
                        nodes[node_id]["children"].append(child_id)
                elif child is not None:
                    child_id = str(child)
                    if child_id not in nodes[node_id]["children"]:
                        nodes[node_id]["children"].append(child_id)
            return node_id

        def visit(value: Any, parent_id: Optional[str] = None) -> None:
            if isinstance(value, dict):
                if self._looks_like_node(value):
                    register(value, parent_id)
                    return
                for key in ["structure", "tree", "root", "data", "result", "nodes", "children", "sections", "items"]:
                    if key in value:
                        visit(value[key], parent_id)
            elif isinstance(value, list):
                for item in value:
                    visit(item, parent_id)

        visit(raw_tree)
        for node_id, node in nodes.items():
            if node.get("parent_id") is None and node_id not in roots:
                roots.append(node_id)

        return {"nodes": nodes, "root_ids": roots}

    @staticmethod
    def _looks_like_node(value: Dict[str, Any]) -> bool:
        return any(
            key in value
            for key in [
                "node_id",
                "id",
                "uuid",
                "title",
                "heading",
                "text",
                "content",
                "summary",
                "prefix_summary",
                "children",
                "nodes",
            ]
        )

    @staticmethod
    def _extract_text_field(value: Dict[str, Any], keys: List[str]) -> str:
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        return ""

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return [token.lower() for token in TOKEN_RE.findall(text)]

    def _overlap_score(self, query: str, node: Dict[str, Any]) -> float:
        query_tokens = set(self._tokenize(query))
        node_tokens = set(
            self._tokenize(
                " ".join(
                    [
                        node.get("title", ""),
                        node.get("summary", ""),
                        node.get("prefix_summary", ""),
                        node.get("text", ""),
                    ]
                )
            )
        )
        if not query_tokens or not node_tokens:
            return 0.0
        return len(query_tokens & node_tokens) / max(len(query_tokens), 1)

    @staticmethod
    def _shorten(text: str, limit: int) -> str:
        text = str(text or "").strip()
        if len(text) <= limit:
            return text
        return text[:limit] + " ..."

    def _ensure_state_file(self) -> None:
        if self.state_cache_path.exists():
            return
        self._save_state(
            {
                "corpus_hash": "",
                "current_corpus_hash": "",
                "tree_cache_stale": False,
                "last_sync_status": "",
                "last_error": "",
                "last_synced_at": "",
            }
        )

    def _load_state(self) -> Dict[str, Any]:
        try:
            return json.loads(self.state_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {
                "corpus_hash": "",
                "current_corpus_hash": "",
                "tree_cache_stale": False,
                "last_sync_status": "",
                "last_error": "",
                "last_synced_at": "",
            }

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_cache_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
