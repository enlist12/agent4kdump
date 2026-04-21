from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class TaintAnalysisObj(BaseModel):
    file_name: str = Field(description="File containing the traced object assignment")
    variable_name: str = Field(description="Variable or state object name")
    line: int = Field(description="1-based source line of the traced object")
    column: Optional[int] = Field(default=None, description="1-based column if known")
    current_function: str = Field(
        description="Function where this object is identified"
    )
    explain: str = Field(
        description="Why this object is relevant and how it propagates"
    )
    end: bool = Field(description="Whether taint tracing should stop")

    def get_prompt(self) -> str:
        col = f":{self.column}" if self.column else ""
        return (
            f"object={self.variable_name}, "
            f"location={self.file_name}:{self.line}{col}, "
            f"function={self.current_function}, "
            f"explain={self.explain}, "
            f"end={self.end}"
        )

    def same_target(self, other: "TaintAnalysisObj") -> bool:
        return (
            self.file_name == other.file_name
            and self.line == other.line
            and self.variable_name == other.variable_name
            and self.current_function == other.current_function
        )


class TaintBranch(BaseModel):
    """Describe one branch created by a conditional taint decision."""

    label: Literal["true", "false", "case", "unknown"] = Field(
        description="Branch label for the conditional path"
    )
    condition: str = Field(description="Conditional expression that split the path")
    assumption: str = Field(description="Local assumption for this branch")
    reason: str = Field(description="Why this branch must be analyzed")
    priority: int = Field(default=0, description="Lower priority is analyzed first")


class TaintStepResult(BaseModel):
    """Represent one taint-analysis step result."""

    kind: Literal["single", "branch", "terminal"] = Field(
        description="Whether the step produced one hop, branches, or a terminal node"
    )
    next_obj: Optional[TaintAnalysisObj] = Field(
        default=None, description="Next taint object for a normal single-hop step"
    )
    branches: List[TaintBranch] = Field(
        default_factory=list, description="Conditional branches to analyze"
    )
    terminal_reason: Optional[str] = Field(
        default=None, description="Why the current branch should stop"
    )


class RootCauseAnalysisResult(BaseModel):
    class CrashSiteDetail(BaseModel):
        file: str = Field(description="Source file of the crash site")
        function: str = Field(description="Function containing the faulting statement")
        line: int = Field(description="1-based source line of the faulting statement")
        statement: str = Field(description="Faulting or near-faulting source statement")
        invalid_object: str = Field(description="Object or state that is invalid at the crash site")

    class ChainStep(BaseModel):
        step: int = Field(description="1-based order in the root-cause chain")
        file: str = Field(description="Source file for this reasoning step")
        function: str = Field(description="Function for this reasoning step")
        line: int = Field(description="Relevant source line for this reasoning step")
        object: str = Field(description="Key object or state for this step")
        explanation: str = Field(description="Why this step matters in the propagation chain")

    class SourceLocation(BaseModel):
        label: str = Field(description="Short label such as dereference, assignment, fetch, or guard")
        file: str = Field(description="Source file")
        function: str = Field(description="Function name")
        line: int = Field(description="1-based source line")
        detail: str = Field(description="Why this location is important")

    class FixCandidate(BaseModel):
        file: str = Field(description="Source file proposed for the fix")
        function: str = Field(description="Function proposed for the fix")
        line: int = Field(description="Approximate insertion or modification line")
        rationale: str = Field(description="Why this is a plausible minimal fix location")

    root_cause: str = Field(
        description="Primary root cause conclusion, including fault type and invalid object/state"
    )
    trigger_path: str = Field(
        description="Ordered execution path (3-6 steps) that leads to the crash"
    )
    evidence: List[str] = Field(
        description="Concrete observations grounding the crash trace and source-level reasoning"
    )
    fix_suggestion: str = Field(
        description="Minimal actionable fix direction tied to the vulnerable logic"
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description="Confidence level for the root-cause conclusion"
    )
    uncertainty: Optional[str] = Field(
        default=None,
        description="Any unresolved ambiguity, missing evidence, or quality warning",
    )
    crash_site: Optional[CrashSiteDetail] = Field(
        default=None,
        description="Structured crash-site information for fast review",
    )
    root_cause_chain: List[ChainStep] = Field(
        default_factory=list,
        description="Ordered source-grounded propagation chain from crash site to earliest credible source",
    )
    source_locations: List[SourceLocation] = Field(
        default_factory=list,
        description="Important source locations worth manual review",
    )
    fix_candidates: List[FixCandidate] = Field(
        default_factory=list,
        description="Most plausible source locations to implement a minimal fix",
    )
    patch_sketch: Optional[str] = Field(
        default=None,
        description="Git diff style demo patch showing the minimal fix direction",
    )
    verification_todo: List[str] = Field(
        default_factory=list,
        description="Remaining checks needed to firm up uncertain parts of the conclusion",
    )


class CrashFingerprint(BaseModel):
    panic_header: str = Field(
        default="",
        description="Primary panic header or oops title",
    )
    fault_type: str = Field(
        default="",
        description="Normalized fault type",
    )
    crash_function: str = Field(
        default="",
        description="Crashing function",
    )
    top_frames: List[str] = Field(
        default_factory=list,
        description="Top semantic frames near the crash site",
    )
    subsystem: Optional[str] = Field(
        default=None,
        description="Best-effort subsystem or module name",
    )
    source_path: Optional[str] = Field(
        default=None,
        description="Best-effort source path such as fs/jfs/jfs_imap.c",
    )
    access_type: Optional[str] = Field(
        default=None,
        description="Best-effort access type such as read, write, execute, free, or unknown",
    )
    title_candidates: List[str] = Field(
        default_factory=list,
        description="Exact or normalized title candidates for syzbot matching",
    )
    keywords: List[str] = Field(
        default_factory=list,
        description="Important search keywords extracted from the crash report",
    )


class SearchQueryRecord(BaseModel):
    query: str = Field(
        default="",
        description="Query string executed by the search agent",
    )
    target_domains: List[str] = Field(
        default_factory=list,
        description="Domains filtered or targeted for this query",
    )
    purpose: str = Field(
        default="",
        description="Why this query was executed",
    )
    observed_result: str = Field(
        default="",
        description="Short summary of observed result count or top findings",
    )


class SearchCandidateMatch(BaseModel):
    url: str = Field(
        default="",
        description="Candidate bug, patch, or discussion URL",
    )
    title: str = Field(
        default="",
        description="Short title or summary of the candidate",
    )
    source: str = Field(
        default="unknown",
        description="Entity type such as syzbot, cve, lore, or git",
    )
    relevance: Literal["high", "medium", "low"] = Field(
        default="low",
        description="Confidence that this candidate is relevant enough to review",
    )
    verdict: Literal["match", "rejected", "needs_more_check"] = Field(
        default="needs_more_check",
        description="Current candidate status",
    )
    reason: str = Field(
        default="",
        description="Why this candidate was accepted or rejected",
    )


class KnownBugAnalysisResult(BaseModel):
    is_known_bug: bool = Field(
        description="True if the crash matches a known CVE or Syzbot bug, False otherwise. BINARY decision only - no ambiguity."
    )
    evidence: str = Field(
        description="The evidence supporting the conclusion. MUST include 4-checkpoint verification (Call Trace, Symptom Match, Patch Verification, Falsification) if is_known_bug=True"
    )
    matched_url: Optional[List[str]] = Field(
        default=None,
        description="The matched CVE URLs or Syzbot URLs or other relevant URLs if is_known_bug is True",
    )
    extra_info: Optional[str] = Field(
        default=None, description="Any additional information or context"
    )
    verification_details: Optional[str] = Field(
        default=None,
        description="Your explicit self-check answers from Phase 4 (REQUIRED if is_known_bug=True)",
    )
    crash_fingerprint: Optional[CrashFingerprint] = Field(
        default=None,
        description="Structured crash signature used to drive the search strategy",
    )
    queries_tried: List[SearchQueryRecord] = Field(
        default_factory=list,
        description="All search queries executed and their observed outcomes",
    )
    candidate_matches: List[SearchCandidateMatch] = Field(
        default_factory=list,
        description="Top reviewed search candidates with acceptance or rejection reasons",
    )
    rejection_summary: Optional[str] = Field(
        default=None,
        description="Why the strongest near-matches were rejected",
    )
    final_reasoning: Optional[str] = Field(
        default=None,
        description="Compact final explanation for the binary known or unknown decision",
    )


class SearchReviewResult(BaseModel):
    agree_with_initial: bool = Field(
        description="Whether reviewer agrees with initial known/unknown decision"
    )
    final_is_known_bug: bool = Field(description="Reviewer's final binary decision")
    review_reason: str = Field(description="Why reviewer agrees/disagrees")
    missing_checks: Optional[List[str]] = Field(
        default=None, description="Missing checks reviewer found"
    )
