from agents.analyze_prompt import (
    TEST_ANALYZE_OBJECT_PROMPT,
    TEST_ANALYZE_TAINT_PROMPT,
    TEST_ANALYZE_ROOT_PROMPT,
)
from agents.search_prompt import COT_PROMPT
from agent_core.model import get_model, MAX_RECURSION_DEPTH
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from agent_core.tools import CUSTOM_AGENT_TOOLS, CODEQUERY_TOOLS
from agent_core.tools.commandTools import build_shell_middleware
from langfuse.langchain import CallbackHandler

ANALYZE_AGENT_TOOLS = list(CUSTOM_AGENT_TOOLS.values()) + list(CODEQUERY_TOOLS.values())

ANALYSIS_MESSAGE = """
Start root cause analysis for this unknown crash.
The bug is already classified as NOT known by search_agent.
"""


class TaintAnalysisObj(BaseModel):
    """One taint-tracing hop, migrated from the external kdump workflow style."""

    file_name: str = Field(description="File containing the traced object definition/assignment")
    variable_name: str = Field(description="Variable or state object name")
    line: int = Field(description="1-based source line of the traced object")
    column: Optional[int] = Field(default=None, description="1-based column if known")
    current_function: str = Field(description="Function where this object is identified")
    explain: str = Field(description="Why this object is relevant and how it propagates")
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


class RootCauseAnalysisResult(BaseModel):
    """Final structured output consumed by main.py."""

    root_cause: str = Field(
        description="Primary root cause conclusion, including fault type and invalid object/state"
    )
    trigger_path: str = Field(
        description="Ordered execution path (3-6 steps) that leads to the crash"
    )
    evidence: List[str] = Field(
        description="Concrete evidence from crash trace and source behavior"
    )
    fix_suggestion: str = Field(
        description="Minimal actionable fix direction with target function/file scope"
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description="Confidence in the root cause conclusion"
    )
    uncertainty: Optional[str] = Field(
        default=None,
        description="Known uncertainty, alternative hypothesis, or missing data"
    )


def parse_analyze_results(results: RootCauseAnalysisResult):
    """Parse structured analyze-agent output for main workflow."""
    return {
        "root_cause": results.root_cause,
        "trigger_path": results.trigger_path,
        "evidence": results.evidence,
        "fix_suggestion": results.fix_suggestion,
        "confidence": results.confidence,
        "uncertainty": results.uncertainty,
    }


def verify_analysis_quality(result: RootCauseAnalysisResult) -> tuple[bool, str]:
    """Final quality gate for root-cause report."""
    if not result.root_cause or len(result.root_cause.strip()) < 20:
        return False, "root_cause is too brief"

    if not result.trigger_path or len(result.trigger_path.strip()) < 30:
        return False, "trigger_path is too brief"

    if not result.evidence or len(result.evidence) < 3:
        return False, "at least 3 evidence items are required"

    weak_evidence_count = sum(1 for item in result.evidence if len(item.strip()) < 10)
    if weak_evidence_count > 0:
        return False, "evidence items must be concrete and non-trivial"

    # Require at least one source-grounded evidence item with file/line style signal.
    grounded = 0
    for item in result.evidence:
        item_l = item.lower()
        if (":" in item and "/" in item) or ("line" in item_l and ("file" in item_l or "/" in item_l)):
            grounded += 1
    if grounded == 0:
        return False, "evidence must include at least one source-grounded item (file/line)"

    if not result.fix_suggestion or len(result.fix_suggestion.strip()) < 20:
        return False, "fix_suggestion is too brief"

    return True, "Result meets quality standards"


def _create_object_agent():
    llm = get_model()
    return create_agent(
        model=llm,
        tools=ANALYZE_AGENT_TOOLS,
        middleware=build_shell_middleware(),
        system_prompt=TEST_ANALYZE_OBJECT_PROMPT,
        response_format=TaintAnalysisObj,
    )


def _create_taint_agent():
    llm = get_model()
    return create_agent(
        model=llm,
        tools=ANALYZE_AGENT_TOOLS,
        middleware=build_shell_middleware(),
        system_prompt=TEST_ANALYZE_TAINT_PROMPT,
        response_format=TaintAnalysisObj,
    )


def _create_root_agent():
    llm = get_model()
    return create_agent(
        model=llm,
        tools=ANALYZE_AGENT_TOOLS,
        middleware=build_shell_middleware(),
        system_prompt=TEST_ANALYZE_ROOT_PROMPT,
        response_format=RootCauseAnalysisResult,
    )


def _build_taint_chain(
    taint_agent,
    first_object: TaintAnalysisObj,
    langfuse_handler: CallbackHandler,
    max_steps: int,
) -> List[TaintAnalysisObj]:
    chain: List[TaintAnalysisObj] = [first_object]

    for step in range(max_steps):
        last_obj = chain[-1]
        if last_obj.end:
            break

        history = "\n".join(
            [f"Step {idx + 1}: {obj.get_prompt()}" for idx, obj in enumerate(chain)]
        )

        prompt = f"""
Reverse taint tracing step {step + 1}.
Find ONE upstream source hop for the current object.

Current object:
{last_obj.get_prompt()}

Existing chain:
{history}

Constraints:
1. One hop only.
2. Keep file_name and line concrete.
3. Set end=true only when you reached likely input/boundary/root condition.
4. If uncertain, explain uncertainty in explain.
"""

        result = taint_agent.invoke(
            {"messages": [HumanMessage(content=prompt + COT_PROMPT)]},
            config={"callbacks": [langfuse_handler], "recursion_limit": MAX_RECURSION_DEPTH},
        )

        if "structured_response" not in result:
            break

        next_obj = result["structured_response"]

        if next_obj.file_name == last_obj.file_name and next_obj.line == last_obj.line and next_obj.variable_name == last_obj.variable_name:
            next_obj.end = True
            next_obj.explain = (
                next_obj.explain
                + " | Stop: tracing converged to same object in consecutive step."
            )

        chain.append(next_obj)

        if next_obj.end:
            break

    return chain


def runAnalyzeAgent(max_retries: int = 2, max_taint_steps: int = 6):
    """
    Run migrated kdump root-cause workflow:
    1) immediate crash object identification
    2) iterative reverse taint tracing
    3) final root-cause synthesis

    Args:
        max_retries: retries for final quality gate.
        max_taint_steps: upper bound of reverse-taint hops.
    """
    object_agent = _create_object_agent()
    taint_agent = _create_taint_agent()
    root_agent = _create_root_agent()
    langfuse_handler = CallbackHandler()

    for attempt in range(max_retries + 1):
        object_prompt = ANALYSIS_MESSAGE + "\nFirst, identify the immediate crash object.\n" + COT_PROMPT

        object_result = object_agent.invoke(
            {"messages": [HumanMessage(content=object_prompt)]},
            config={"callbacks": [langfuse_handler], "recursion_limit": MAX_RECURSION_DEPTH},
        )

        if "structured_response" not in object_result:
            if attempt < max_retries:
                continue
            return None

        first_object: TaintAnalysisObj = object_result["structured_response"]
        taint_chain = _build_taint_chain(
            taint_agent=taint_agent,
            first_object=first_object,
            langfuse_handler=langfuse_handler,
            max_steps=max_taint_steps,
        )

        chain_text = "\n".join(
            [f"Step {idx + 1}: {obj.get_prompt()}" for idx, obj in enumerate(taint_chain)]
        )

        root_prompt = f"""
Unknown-bug root cause finalization.
You now have the taint chain below:

{chain_text}

Requirements:
1. root_cause must mention fault type + invalid object/state.
2. trigger_path must be ordered and concise.
3. evidence must include crash-trace and source-level observations.
4. fix_suggestion must be minimal and actionable.
5. confidence must be low/medium/high.
6. If chain is incomplete, explain uncertainty explicitly.
"""

        root_result = root_agent.invoke(
            {"messages": [HumanMessage(content=root_prompt + COT_PROMPT)]},
            config={"callbacks": [langfuse_handler], "recursion_limit": MAX_RECURSION_DEPTH},
        )

        if "structured_response" not in root_result:
            if attempt < max_retries:
                continue
            return None

        structured_result: RootCauseAnalysisResult = root_result["structured_response"]
        is_valid, reason = verify_analysis_quality(structured_result)

        if is_valid:
            chain_summary = f"Taint chain length={len(taint_chain)}; terminal_end={taint_chain[-1].end}."
            if structured_result.uncertainty:
                structured_result.uncertainty = structured_result.uncertainty + " | " + chain_summary
            else:
                structured_result.uncertainty = chain_summary
            return structured_result

        if attempt < max_retries:
            continue

        if structured_result.uncertainty:
            structured_result.uncertainty = structured_result.uncertainty + f" | Quality check warning: {reason}"
        else:
            structured_result.uncertainty = f"Quality check warning: {reason}"
        return structured_result

    return None
