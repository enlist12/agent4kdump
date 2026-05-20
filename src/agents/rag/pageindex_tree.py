import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from pageindex.page_index_md import md_to_tree
    from pageindex.utils import ConfigLoader
except Exception:  # PageIndex is optional at runtime.
    md_to_tree = None
    ConfigLoader = None

TOKEN_RE = re.compile(r"[a-zA-Z0-9_./:-]+")
CASE_ID_RE = re.compile(r"\bcase_[0-9a-f]{12}\b")
STATE_DEFAULT = {
    "corpus_hash": "",
    "current_corpus_hash": "",
    "tree_cache_stale": False,
    "last_sync_status": "",
    "last_error": "",
    "last_synced_at": "",
}


class PageIndexTreeRetriever:
    """Cache a PageIndex markdown tree and retrieve relevant nodes by lexical overlap."""

    def __init__(self, base_dir: Path, logger: Any, enabled: bool = True) -> None:
        self.base_dir = Path(base_dir)
        self.logger = logger
        self.enabled = enabled
        self.pageindex_api_key = os.environ.get("PAGEINDEX_API_KEY", "").strip()
        self.tree_cache_path = self.base_dir / "pageindex_tree.json"
        self.state_cache_path = self.base_dir / "pageindex_state.json"
        self._current_corpus_info = {
            "exists": False,
            "record_count": 0,
            "corpus_hash": "",
            "corpus_path": self.base_dir / "history_corpus.md",
        }
        if not os.environ.get("OPENAI_API_KEY"):
            fallback = os.environ.get("API_KEY") or os.environ.get("CHATGPT_API_KEY")
            if fallback:
                os.environ["OPENAI_API_KEY"] = fallback
        if not os.environ.get("OPENAI_API_BASE") and os.environ.get("LLM_BASE_URL"):
            os.environ["OPENAI_API_BASE"] = os.environ["LLM_BASE_URL"]
        if not self.state_cache_path.exists():
            self._save_state(dict(STATE_DEFAULT))

    def mark_corpus_state(self, corpus_info: dict[str, Any]) -> None:
        self._current_corpus_info = dict(corpus_info)
        state = self._load_state()
        has_history = bool(corpus_info.get("exists"))
        current_hash = str(corpus_info.get("corpus_hash", ""))

        if not has_history:
            if self.tree_cache_path.exists():
                self.tree_cache_path.unlink()
            state.update(STATE_DEFAULT | {"last_sync_status": "no_history"})
        else:
            state["current_corpus_hash"] = current_hash
            state["tree_cache_stale"] = (
                not self.tree_cache_path.exists() or state.get("corpus_hash") != current_hash
            )
            if not state["tree_cache_stale"]:
                state["last_sync_status"] = "cache_ready"
                state["last_error"] = ""
        self._save_state(state)

    def sync_history_tree(self, corpus_info: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if corpus_info is not None:
            self._current_corpus_info = dict(corpus_info)
        info = self._current_corpus_info
        state = self._load_state()

        if not self.enabled:
            return self._save_status(state, "disabled", "PageIndex disabled by configuration.")
        if not info.get("exists"):
            state.update(STATE_DEFAULT | {"last_sync_status": "no_history"})
            self._save_state(state)
            return state
        if md_to_tree is None or ConfigLoader is None:
            return self._save_status(
                state, "backend_missing", "PageIndex markdown backend is unavailable."
            )

        current_hash = str(info.get("corpus_hash", ""))
        if self.tree_cache_path.exists() and state.get("corpus_hash") == current_hash:
            state.update(
                {
                    "current_corpus_hash": current_hash,
                    "tree_cache_stale": False,
                    "last_sync_status": "cache_ready",
                    "last_error": "",
                }
            )
            self._save_state(state)
            return state

        try:
            opt = ConfigLoader().load({})
            raw_tree = asyncio.run(
                md_to_tree(
                    md_path=str(info["corpus_path"]),
                    if_thinning=False,
                    min_token_threshold=5000,
                    if_add_node_summary=opt.if_add_node_summary,
                    summary_token_threshold=200,
                    model=opt.model,
                    if_add_doc_description=opt.if_add_doc_description,
                    if_add_node_text=opt.if_add_node_text,
                    if_add_node_id=opt.if_add_node_id,
                )
            )
        except Exception as exc:
            self.logger.warning("PageIndex markdown tree generation failed: %s", exc)
            return self._save_status(
                state, "local_backend_failed", f"PageIndex markdown tree generation failed: {exc}"
            )

        self.tree_cache_path.write_text(
            json.dumps(raw_tree, ensure_ascii=False, indent=2), encoding="utf-8"
        )
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

    def retrieve_from_tree(self, query: str, top_k: int) -> list[dict[str, Any]]:
        if not self.tree_cache_path.exists():
            return []
        try:
            normalized = self._normalize_tree(
                json.loads(self.tree_cache_path.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError) as exc:
            self.logger.warning("Failed to read tree cache: %s", exc)
            return []

        ranked = sorted(
            [(overlap_score(query, node), node) for node in normalized["nodes"].values()],
            key=lambda item: item[0],
            reverse=True,
        )
        selected = [(score, node) for score, node in ranked if score > 0][:top_k]
        self.logger.info(
            "PageIndex tree lexical search selected node ids: %s",
            [node["node_id"] for _, node in selected],
        )
        hits: list[dict[str, Any]] = []
        for rank, (score, node) in enumerate(selected, 1):
            text = node.get("text", "")
            summary = node.get("summary") or node.get("prefix_summary") or node.get("title") or text
            current_id = node["node_id"]
            case_id = ""
            while current_id:
                current_node = normalized["nodes"].get(current_id) or {}
                match = CASE_ID_RE.search(
                    " ".join(
                        str(current_node.get(key, ""))
                        for key in ["title", "summary", "prefix_summary", "text"]
                    )
                )
                if match:
                    case_id = match.group(0)
                    break
                current_id = current_node.get("parent_id")
            hits.append(
                {
                    "case_id": case_id,
                    "summary": shorten(summary, 500),
                    "root_cause": "",
                    "trigger_path": "",
                    "case_signature": "",
                    "reusable_playbook": [],
                    "applicability": [],
                    "non_applicability": [],
                    "confidence": "reference",
                    "score": max(1.0 - (rank - 1) * 0.1, 0.1) + score,
                    "source": "pageindex_tree",
                    "node_id": node["node_id"],
                    "title": node.get("title", ""),
                    "text": shorten(text, 800),
                    "line_num": node.get("line_num"),
                }
            )
        return hits

    def get_runtime_status(self, corpus_info: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if corpus_info is not None:
            self._current_corpus_info = dict(corpus_info)
        state = self._load_state()
        current_hash = str(self._current_corpus_info.get("corpus_hash", "")) or str(
            state.get("current_corpus_hash", "")
        )
        has_history = bool(self._current_corpus_info.get("exists"))
        tree_exists = self.tree_cache_path.exists()
        tree_stale = bool(
            has_history and (not tree_exists or state.get("corpus_hash") != current_hash)
        )
        ready = bool(has_history and tree_exists and not tree_stale)

        fallback = ""
        if not self.enabled:
            fallback = "PageIndex disabled by configuration."
        elif md_to_tree is None:
            fallback = "PageIndex markdown backend is unavailable."
        elif has_history and state.get("last_error") and not ready:
            fallback = str(state.get("last_error"))
        elif has_history and not ready:
            fallback = "History tree is not ready; falling back to local experience retrieval."

        return {
            "enabled": self.enabled,
            "api_key_configured": bool(self.pageindex_api_key),
            "markdown_backend_ready": md_to_tree is not None,
            "tree_cache_ready": ready,
            "tree_cache_stale": tree_stale,
            "last_sync_status": state.get("last_sync_status", ""),
            "fallback_reason": fallback,
        }

    def _normalize_tree(self, raw_tree: Any) -> dict[str, Any]:
        nodes: dict[str, dict[str, Any]] = {}
        roots: list[str] = []

        def register(raw: dict[str, Any], parent_id: Optional[str]) -> str:
            node_id = str(
                raw.get("node_id")
                or raw.get("id")
                or raw.get("uuid")
                or raw.get("key")
                or hashlib.md5(
                    json.dumps(raw, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()[:12]
            )
            node = nodes.setdefault(
                node_id,
                {
                    "node_id": node_id,
                    "title": first_text(raw, ["title", "name", "heading", "label"]),
                    "summary": first_text(raw, ["summary", "abstract", "description"]),
                    "prefix_summary": first_text(raw, ["prefix_summary"]),
                    "text": first_text(raw, ["text", "content", "body", "markdown", "value"]),
                    "line_num": raw.get("line_num")
                    or raw.get("line")
                    or (raw.get("metadata", {}) or {}).get("line_num"),
                    "children": [],
                    "parent_id": parent_id,
                },
            )
            if parent_id and not node.get("parent_id"):
                node["parent_id"] = parent_id
            if parent_id is None and node_id not in roots:
                roots.append(node_id)
            for child in raw.get("children") or raw.get("nodes") or raw.get("sections") or []:
                child_id = register(child, node_id) if isinstance(child, dict) else str(child)
                if child_id not in node["children"]:
                    node["children"].append(child_id)
            return node_id

        def visit(value: Any, parent_id: Optional[str] = None) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item, parent_id)
            elif isinstance(value, dict) and looks_like_node(value):
                register(value, parent_id)
            elif isinstance(value, dict):
                for key in [
                    "structure",
                    "tree",
                    "root",
                    "data",
                    "result",
                    "nodes",
                    "children",
                    "sections",
                    "items",
                ]:
                    if key in value:
                        visit(value[key], parent_id)

        visit(raw_tree)
        roots.extend(
            node_id
            for node_id, node in nodes.items()
            if node.get("parent_id") is None and node_id not in roots
        )
        return {"nodes": nodes, "root_ids": roots}

    def _save_status(self, state: dict[str, Any], status: str, error: str) -> dict[str, Any]:
        state.update({"tree_cache_stale": True, "last_sync_status": status, "last_error": error})
        self._save_state(state)
        return state

    def _load_state(self) -> dict[str, Any]:
        try:
            return STATE_DEFAULT | json.loads(self.state_cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(STATE_DEFAULT)

    def _save_state(self, state: dict[str, Any]) -> None:
        self.state_cache_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )


def looks_like_node(value: dict[str, Any]) -> bool:
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
            "children",
            "nodes",
        ]
    )


def first_text(value: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(text or ""))]


def overlap_score(query: str, node: dict[str, Any]) -> float:
    query_tokens = set(tokenize(query))
    node_tokens = set(
        tokenize(
            " ".join(
                str(node.get(key, "")) for key in ["title", "summary", "prefix_summary", "text"]
            )
        )
    )
    return (
        len(query_tokens & node_tokens) / max(len(query_tokens), 1)
        if query_tokens and node_tokens
        else 0.0
    )


def shorten(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit] + " ..."
