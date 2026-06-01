from agents.search_prompt import COT_PROMPT, ENHANCE_PROMPT, SEARCH_PROMPT
from agents.utils.model import get_model
from .runtime_config import get_invoke_config
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from typing import Optional, List
from uuid import uuid4
from langgraph.checkpoint.memory import MemorySaver
from agents.tools import CUSTOM_AGENT_TOOLS, CODEQUERY_TOOLS
from agents.tools.commandTools import build_shell_middleware
from langfuse.langchain import CallbackHandler

from .schemas import KnownBugAnalysisResult, SearchReviewResult

SEARCH_AGENT_TOOLS = list(CUSTOM_AGENT_TOOLS.values()) + list(CODEQUERY_TOOLS.values())

def parse_search_results(results: KnownBugAnalysisResult):
    """Parse the search results and return a structured response."""
    return results.model_dump()


def _has_substantive_text(text: Optional[str], min_length: int = 50) -> bool:
    return bool(text and len(text.strip()) >= min_length)


def verify_result_quality(result: KnownBugAnalysisResult) -> tuple[bool, str]:
    """
    Verify if the result meets quality standards.
    Returns: (is_valid, reason)
    """
    fingerprint = result.crash_fingerprint
    if not fingerprint.crash_function or not fingerprint.fault_type:
        return False, "crash_fingerprint must include at least crash_function and fault_type"

    # If claiming it's a known bug, must meet strict requirements
    if result.is_known_bug:
        if not result.matched_url or len(result.matched_url) == 0:
            return False, "No matched URLs provided for claimed known bug"

        if not _has_substantive_text(result.evidence, min_length=30):
            return False, "Known-bug conclusion must include substantive evidence"
    else:
        # If claiming no match, must show sufficient search effort
        informative_queries = sum(
            1
            for item in result.queries_tried
            if item.query.strip() and item.observed_result.strip()
        )
        if informative_queries < 2:
            return (
                False,
                "When reporting is_known_bug=False, must document at least two concrete search attempts in queries_tried",
            )

        if not _has_substantive_text(result.evidence, min_length=30):
            return False, "Unknown-bug conclusion must include substantive evidence"

    return True, "Result meets quality standards"


def create_search_reviewer_agent():
    """Create a reviewer agent to cross-check initial search decision semantically."""
    llm = get_model()
    reviewer_prompt = (
        SEARCH_PROMPT
        + ENHANCE_PROMPT
        + """

You are a SECOND-PASS reviewer.
Your job is NOT to do fresh exhaustive search, but to verify whether the initial decision
is semantically justified by evidence quality.

Review rules:
1. Check if crash_fingerprint is concrete enough to support the query plan.
2. Check if links are verifiable bug/commit/CVE entities.
3. Check if call-trace/symptom statements are consistent with linked evidence.
4. Check if the recorded query history and evidence support the binary decision.
5. Check if patch-presence (patched/unpatched) verification is explicit when is_known_bug=True.
6. Keep binary output and list missing checks if any.
"""
    )

    return create_agent(
        model=llm,
        tools=SEARCH_AGENT_TOOLS,
        middleware=build_shell_middleware(),
        system_prompt=reviewer_prompt,
        response_format=SearchReviewResult,
    )


def create_search_agent():
    """Create the search agent with configured tools and prompts."""
    llm = get_model()
    memory = MemorySaver()
    tools = SEARCH_AGENT_TOOLS

    agent_graph = create_agent(
        model=llm,
        tools=tools,
        middleware=build_shell_middleware(),
        system_prompt=SEARCH_PROMPT,
        response_format=KnownBugAnalysisResult,
        checkpointer=memory,
    )

    return agent_graph


def runSearchAgent(max_retries: int = 2):
    """
    Run the search agent with retry mechanism.

    Args:
        max_retries: Maximum number of retries if result quality is insufficient
    """
    agent = create_search_agent()
    reviewer = create_search_reviewer_agent()
    langfuse_handler = CallbackHandler()
    search_thread_id = f"search-agent-{uuid4().hex}"

    for attempt in range(max_retries):
        if attempt == 0:
            messages = [
                HumanMessage(
                    content=(
                        "Start analysis. Determine if this crash is a known bug (CVE/Syzbot).\n\n"
                        f"{COT_PROMPT}"
                    )
                )
            ]
        else:
            retry_message = f"""
RETRY ATTEMPT {attempt}/{max_retries}

Your previous result did not meet quality standards. Please:
1. Reuse the crash fingerprint and useful prior search context from this thread.
2. Address the specific issue below instead of restarting from scratch.
3. Your final structured output MUST include crash_fingerprint again, even if it already appeared earlier in this thread.
4. If claiming a match (is_known_bug=True), ensure the linked public evidence clearly matches the crash signature.
5. If evidence is weak or ambiguous, return is_known_bug=False.

Previous issue: {retry_reason}
"""
            messages = [HumanMessage(content=retry_message)]

        result = agent.invoke(
            {"messages": messages},
            config=get_invoke_config(
                configurable={"thread_id": search_thread_id},
                callbacks=[langfuse_handler],
            ),
        )

        # Extract the structured response
        if "structured_response" not in result:
            if attempt < max_retries:
                retry_reason = "No structured response returned"
                continue
            return None

        structured_result = result["structured_response"]

        # Verify result quality
        is_valid, reason = verify_result_quality(structured_result)

        if not is_valid:
            print(f"[Search Agent] Attempt {attempt + 1} failed quality check: {reason}")
            if attempt < max_retries:
                retry_reason = reason
                continue
            else:
                # After max retries, if still claiming known bug but low quality, downgrade to unknown
                if structured_result.is_known_bug:
                    print(
                        f"[Search Agent] Max retries reached. Downgrading to 'unknown bug' due to insufficient verification."
                    )
                    structured_result.is_known_bug = False
                    structured_result.evidence = (
                        f"INSUFFICIENT VERIFICATION ({reason}): {structured_result.evidence}"
                    )
                return structured_result

        # Second-pass semantic review for stability (workflow-based, no regex shortcuts)
        review_prompt = f"""
Please review the initial decision below and decide whether it is semantically justified.

Initial decision:
- is_known_bug: {structured_result.is_known_bug}
- crash_fingerprint: {structured_result.crash_fingerprint}
- queries_tried: {structured_result.queries_tried}
- matched_url: {structured_result.matched_url}
- evidence: {structured_result.evidence}
"""

        review_result = reviewer.invoke(
            {"messages": [HumanMessage(content=review_prompt + COT_PROMPT)]},
            config=get_invoke_config(callbacks=[langfuse_handler]),
        )

        if "structured_response" in review_result:
            review_struct = review_result["structured_response"]
            reviewer_disagree = (not review_struct.agree_with_initial) or (
                review_struct.final_is_known_bug != structured_result.is_known_bug
            )

            if reviewer_disagree:
                review_reason = review_struct.review_reason
                missing = (
                    ", ".join(review_struct.missing_checks)
                    if review_struct.missing_checks
                    else "none"
                )
                print(
                    f"[Search Agent] Attempt {attempt + 1} reviewer disagreement: {review_reason}; missing_checks={missing}"
                )
                if attempt < max_retries:
                    retry_reason = (
                        f"Reviewer disagreement: {review_reason}; missing_checks={missing}"
                    )
                    continue

                # Conservative fallback after retries: prefer unknown instead of false known-bug claim
                if structured_result.is_known_bug and not review_struct.final_is_known_bug:
                    structured_result.is_known_bug = False
                    structured_result.evidence = (
                        "INSUFFICIENT VERIFICATION "
                        f"(reviewer disagreement: {review_reason}; missing_checks={missing}): "
                        f"{structured_result.evidence}"
                    )
                else:
                    structured_result.evidence = (
                        f"{structured_result.evidence}\n\n"
                        f"Reviewer note: {review_reason}; missing_checks={missing}"
                    )
                return structured_result

        return structured_result

    return None
