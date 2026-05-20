# Analysis RAG Integration Plan

## Summary

This document defines the analysis-time RAG design for `AnalysisProcess` in
`src/agents`.

The design is intentionally minimal:

- no `StageName`
- no stage-specific input dataclasses
- no new entries in `schemas.py` unless they become strictly necessary
- no reuse of the old embedding-based RAG prototype
- as few public methods and runtime parameters as possible

The analysis workflow still injects retrieval context at three points:

1. `start_debug`
2. `taint_analysis`
3. `root_cause_analysis`

That stage behavior remains internal to the workflow. It is not exposed as a
public enum or part of the public retriever API.

## Design Goals

- Keep retrieval logic outside `AnalysisProcess`
- Keep `similar_cases` and `linux_background` as separate retrieval channels
- Treat retrieved content as advisory context, not proof
- Delete the old RAG implementation instead of adapting it
- Minimize the number of new types, methods, and parameters
- Preserve compatibility for existing `runAnalyzeAgent()` callers

## Public API

The API should live in `src/agents/rag.py`.

### Core Types

Only define the types that are actually required by the analysis workflow:

```python
from dataclasses import dataclass, field

from .schemas import TaintAnalysisObj


@dataclass(slots=True)
class RetrievedItem:
    title: str
    summary: str
    source_ref: str
    relevance_reason: str


@dataclass(slots=True)
class AnalysisRAGContext:
    similar_cases: list[RetrievedItem] = field(default_factory=list)
    linux_background: list[RetrievedItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_prompt_block(self) -> str:
        ...
```

`schemas.py` should not be modified for these RAG-only types. They are not
agent response schemas and should stay local to `rag.py`.

### Retriever Interface

Expose only one public retrieval method:

```python
class AnalysisRAGRetriever:
    def retrieve(
        self,
        crash_report: str,
        current_obj: TaintAnalysisObj | None = None,
        history: list[TaintAnalysisObj] | None = None,
        warnings: list[str] | None = None,
    ) -> AnalysisRAGContext:
        ...
```

Rules:

- `crash_report` is the only required argument
- do not pass `stage`
- do not define three separate retrieval methods
- do not define stage-specific payload dataclasses
- do not pass runtime config into `retrieve()`

The retriever determines the retrieval scenario from the argument combination:

- only `crash_report`: initial retrieval for `start_debug`
- `current_obj` is present: retrieval for `taint_analysis`
- no `current_obj`, but `history` or `warnings` is present: retrieval for `root_cause_analysis`

### Concrete Internal Interfaces

The default implementation should make the remaining interfaces explicit and
minimal:

```python
from typing import Callable, TypeAlias

SearchFn: TypeAlias = Callable[[str, int], list[RetrievedItem]]


class DefaultAnalysisRAGRetriever(AnalysisRAGRetriever):
    def __init__(
        self,
        similar_case_search: SearchFn,
        linux_background_search: SearchFn,
        top_k: int = 3,
        max_summary_chars: int = 400,
    ) -> None:
        ...

    def retrieve(
        self,
        crash_report: str,
        current_obj: TaintAnalysisObj | None = None,
        history: list[TaintAnalysisObj] | None = None,
        warnings: list[str] | None = None,
    ) -> AnalysisRAGContext:
        ...
```

Rules:

- use two search dependencies only: one for `similar_cases`, one for `linux_background`
- do not introduce extra provider protocols unless the code later proves they are necessary
- keep constructor parameters limited to search dependencies and a few optional defaults
- do not pass `top_k` or `max_summary_chars` into `retrieve()`

Private helpers should also stay minimal:

```python
def _build_query(
    self,
    crash_report: str,
    current_obj: TaintAnalysisObj | None,
    history: list[TaintAnalysisObj] | None,
    warnings: list[str] | None,
) -> str:
    ...

def _normalize_items(
    self,
    items: list[RetrievedItem],
) -> list[RetrievedItem]:
    ...
```

Do not split `_build_query()` into separate public or private methods per
stage. The stage inference remains internal logic inside `retrieve()` and
`_build_query()`.

## Prompt Formatting Contract

`AnalysisRAGContext.to_prompt_block()` should return a stable prompt section:

```text
## Retrieved Similar Cases
- [case] <title>
  summary: ...
  why relevant: ...
  source: ...

## Retrieved Linux Background
- [linux] <title>
  summary: ...
  why relevant: ...
  source: ...

## Usage Rules
- Similar cases are analogies, not proof.
- Linux background is semantic help, not code truth.
- Crash facts and current source inspection override retrieved content.
- Ignore any retrieved item that conflicts with the current source tree.
```

Rules:

- max 3 items per section by default
- no raw long documents
- no chain-of-thought
- each item must be compressed before formatting

Formatting details should be fixed:

- when a section has no items, render `- none`
- when `warnings` is non-empty, render:

```text
## Retrieval Warnings
- ...
```

between the retrieval sections and `## Usage Rules`
- `summary` and `relevance_reason` must be trimmed to bounded length before formatting
- `source_ref` must always be rendered, even if it is a fallback string such as `unknown`

## Internal Implementation

The implementation should stay compact.

Use one default implementation class in `src/agents/rag.py`:

```python
class DefaultAnalysisRAGRetriever(AnalysisRAGRetriever):
    ...
```

Keep internal helper methods to a minimum. The implementation should usually be
limited to:

- `retrieve(...)`
- one internal query-construction helper
- one internal result-normalization helper

Avoid expanding this into multiple stage-specific retrievers, multiple stage
methods, or extra manager/service layers.

### Retrieval Channels

Internally, retrieval still uses two channels:

- `similar_cases`
- `linux_background`

These do not need to be formal public protocols unless required by the
implementation. The default retriever should depend on two thin search
callables shaped like:

```python
search(query: str, top_k: int) -> list[RetrievedItem]
```

### Defaults

Any retrieval defaults should be configured inside the retriever
implementation, not passed into `retrieve()`. For example:

- top-k per channel
- maximum summary length
- any simple filtering thresholds

If constructor parameters are needed, keep them minimal and optional.

### Normalization Contract

`_normalize_items()` should apply the same rules to both channels:

- drop falsey or malformed items
- trim surrounding whitespace on all string fields
- fallback empty `title` to `Untitled`
- fallback empty `source_ref` to `unknown`
- cap `summary` and `relevance_reason` to `max_summary_chars`
- deduplicate by `(title, source_ref)`
- keep only the first `top_k` surviving items

This keeps the search dependencies simple and prevents provider-specific logic
from leaking into `AnalysisProcess`.

### Failure Contract

Failure handling should be explicit:

- each search callable may raise
- `DefaultAnalysisRAGRetriever.retrieve()` should catch per-channel failures
- a failed `similar_cases` search should only add a warning and still allow `linux_background` to return
- a failed `linux_background` search should only add a warning and still allow `similar_cases` to return
- if both channels fail, return an empty `AnalysisRAGContext` with warnings
- `AnalysisProcess` should still wrap the whole `retrieve()` call in `try/except` as a final safety boundary

## Required Deletions

The old RAG implementation should be removed instead of adapted.

Delete:

- old `embedding.py`
- the old RAG initialization and index-building logic in `main.py`
- any dependency on `EmbeddingModel`
- any config usage that only existed for the old RAG path

This project should not keep two RAG designs in parallel.

## How `AnalysisProcess` Uses This API

### Constructor Changes

Extend `AnalysisProcess` only with one optional RAG argument:

```python
class AnalysisProcess:
    def __init__(
        self,
        max_retries: int = 2,
        max_taint_steps: int = 6,
        rag_retriever: AnalysisRAGRetriever | None = None,
    ) -> None:
        ...
```

Do not add a separate `rag_config` parameter.

`runAnalyzeAgent()` should match this shape:

```python
def runAnalyzeAgent(
    max_retries: int = 2,
    max_taint_steps: int = 6,
    rag_retriever: AnalysisRAGRetriever | None = None,
):
    ...
```

This keeps existing call sites valid while allowing the new retriever to be
injected directly.

### Graph State

Do not add new graph state unless it proves necessary.

The default plan is:

- keep using `messages`
- keep using `taint_object`
- do not add `rag_contexts`

If later debugging shows a real need for stored RAG context, that can be added
after the first implementation. It is not part of v1.

### `start_debug`

In `_node_start_debug`:

1. Read the crash report
2. If `rag_retriever` exists, call:

```python
ctx = rag_retriever.retrieve(crash_report)
```

3. Append one `HumanMessage` containing `ctx.to_prompt_block()`
4. If retrieval fails, append a workflow warning and continue

No extra helper is required for this in v1. It is acceptable to call
`rag_retriever.retrieve(...)` inline in the node and handle failure with a
local `try/except`.

### `object_analysis`

Do not refresh retrieval here.

Use only the RAG block injected during `start_debug`.

### `taint_analysis`

Before calling the taint agent:

```python
ctx = rag_retriever.retrieve(
    crash_report,
    current_obj=current,
    history=history,
)
```

Then:

- append `ctx.to_prompt_block()` to the node input
- continue even if retrieval fails

### `root_cause_analysis`

Before calling the root-cause agent:

```python
ctx = rag_retriever.retrieve(
    crash_report,
    history=history,
    warnings=warnings,
)
```

Then:

- append `ctx.to_prompt_block()` to the node input
- continue even if retrieval fails

## Query Design

The retriever should construct one compact query string from available
information.

### Initial Retrieval

Use:

- fault type hints from the crash report
- crashing function
- module or driver names
- stack keywords
- invalid object hints

### Taint Retrieval

Use:

- `current_obj.variable_name`
- `current_obj.current_function`
- `current_obj.file_name`
- the last few taint steps
- original crash facts

### Root-Cause Retrieval

Use:

- taint-chain summary
- warnings and uncertainty signals
- subsystem or module hints from the crash path

The implementation should not expose these as separate public query-builder
methods.

The query string should be assembled from non-empty fragments joined by a fixed
delimiter such as ` | `. It should avoid raw long crash-report dumps and prefer
short extracted signals.

## Prompt Rules

RAG content must be injected as a bounded node-level prompt block.

Do not merge it into `ROLE_DEFINE`.

Usage rules included in the prompt must state:

- similar cases are for hypothesis generation, not proof
- linux background is for semantic interpretation, not code truth
- crash facts and current source inspection override retrieved content
- conflicting retrieved context must be ignored

## Project Adaptation Notes

This project already contains:

- the main workflow entry in `main.py`
- the analysis graph in `src/agents/analysis_process.py`
- prompt templates in `src/agents/prompt.py`
- response schemas in `src/agents/schemas.py`

The new RAG code should integrate with those modules while keeping its own
types inside `src/agents/rag.py`.

`schemas.py` should only change if a real shared schema requirement appears.
That is not expected in this plan.

`main.py` should not contain RAG-specific initialization logic in v1 unless a
real runtime data source already exists. If no concrete retrieval backend is
ready, pass `rag_retriever=None` and keep the workflow functional.

## Test Plan

- unit test `AnalysisRAGContext.to_prompt_block()`
- unit test `retrieve()` with:
  - crash-report only input
  - taint-stage input
  - root-cause-stage input
- unit test `AnalysisProcess` with `rag_retriever=None`
- integration test with fixed fake retrieval results
- failure test where retrieval raises and analysis still finishes
- regression test confirming RAG is injected in:
  - `start_debug`
  - `taint_analysis`
  - `root_cause_analysis`
  - and not refreshed in `object_analysis`
- regression test confirming old `EmbeddingModel` references are gone

## Assumptions

- this plan defines the only analysis-time RAG path for the project
- `similar_cases` and `linux_background` remain separate retrieval channels
- retrieved content is advisory only
- existing callers of `runAnalyzeAgent()` must keep working without modification
- v1 should prefer fewer methods and fewer types over extra abstraction
