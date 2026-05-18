# RAG Slimming Notes

## Current role
The `agents.rag` package is an optional experience-retrieval layer used by `main.py` before and after root-cause analysis.

## External interfaces to preserve

### Package export
- `from agents.rag import AnalysisRAGManager`

### `AnalysisRAGManager(base_dir="./cache/rag", use_pageindex=True)`
Creates the RAG manager, prepares the local experience corpus, and optionally keeps a PageIndex markdown tree cache in sync.

### `build_pre_analysis_context(crash_report: str, top_k: int = 3) -> dict`
Called before `runAnalyzeAgent`. Returned keys must remain:
- `profile`: extracted crash metadata (`kernel_version`, `bug_type`, `functions`, `modules`, `driver_candidates`, `keywords`)
- `query`: retrieval query string built from the profile and crash excerpt
- `experience_hits`: historical case hits from PageIndex tree or local lexical fallback
- `linux_background`: optional web background snippets
- `context`: final text injected into the analysis prompt

### `persist_success_case(crash_report: str, analysis_result: dict, trace: dict | None, retrieved_context: dict | None) -> str`
Called after a successful analysis. It must persist:
- JSONL record in `experience_store.jsonl`
- markdown case card under `experience_docs/`
- aggregate `history_corpus.md` for PageIndex tree generation
It returns a stable-looking `case_<12 hex>` id.

### `get_pageindex_runtime_status() -> dict`
Used by `main.py` for CLI status rendering. Required keys:
- `enabled`
- `api_key_configured`
- `markdown_backend_ready`
- `tree_cache_ready`
- `tree_cache_stale`
- `last_sync_status`
- `fallback_reason`

## Internal modules
- `context_builder.py`: orchestration, profile extraction, local lexical retrieval, final context rendering, deterministic lesson generation.
- `experience_store.py`: JSONL/markdown persistence and corpus rendering.
- `pageindex_tree.py`: optional PageIndex markdown-tree cache plus lexical node retrieval.
- `linux_background.py`: optional Tavily/WebSearch-based kernel background collection.

## Slimming decisions
1. Remove RAG-internal LLM agents for profile extraction, context summarization, and lesson distillation. They added latency and multiple correction/fallback paths while duplicating deterministic summaries.
2. Keep the public output shape stable and render deterministic context sections instead of asking a model to re-summarize retrieved text.
3. Keep PageIndex only as a markdown-tree builder/cache. Replace LLM node selection with lexical overlap ranking.
4. Keep minimal error handling only around external boundaries: filesystem JSON, PageIndex generation, and optional web search.
5. Inline short helpers when they are single-use; retain only shared helpers such as tokenization, shortening, and markdown bullets.
6. Keep separate files where responsibilities are clear (`context_builder`, `experience_store`, `pageindex_tree`, `linux_background`); avoid creating tiny prompt/schema files because RAG no longer needs model schemas.
