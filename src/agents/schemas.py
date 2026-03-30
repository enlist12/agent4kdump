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


class RootCauseAnalysisResult(BaseModel):
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


class SearchReviewResult(BaseModel):
    agree_with_initial: bool = Field(
        description="Whether reviewer agrees with initial known/unknown decision"
    )
    final_is_known_bug: bool = Field(description="Reviewer's final binary decision")
    review_reason: str = Field(description="Why reviewer agrees/disagrees")
    missing_checks: Optional[List[str]] = Field(
        default=None, description="Missing checks reviewer found"
    )
