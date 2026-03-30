import build

from agents.search_prompt import COT_PROMPT, ENHANCE_PROMPT, SEARCH_PROMPT
from agent_core.model import get_model,MAX_RECURSION_DEPTH
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from typing import Optional, List
from pydantic import BaseModel, Field
from agent_core.tools import CUSTOM_AGENT_TOOLS, CODEQUERY_TOOLS
from agent_core.tools.commandTools import build_shell_middleware
from langfuse.langchain import CallbackHandler

from .schemas import KnownBugAnalysisResult,SearchReviewResult

SEARCH_AGENT_TOOLS = list(CUSTOM_AGENT_TOOLS.values()) + list(CODEQUERY_TOOLS.values())

ANALYSIS_MESSAGE = """
Start analysis. Determine if this crash is a known bug (CVE/Syzbot).
"""



@tool
def submit_known_bug_analysis(
    is_known_bug: bool,
    evidence: str,
    matched_url: Optional[List[str]] = None,
    extra_info: Optional[str] = None,
    verification_details: Optional[str] = None
):
    """
    Submit the final analysis result.
    Call this tool ONLY when you have completed Phase 4 self-verification.
    
    Args:
        is_known_bug: True if match found (score ≥30/40 AND symptom match AND source is vulnerable), False otherwise. BINARY decision required.
        evidence: Complete explanation with 4-checkpoint analysis (Call Trace, Symptom, Patch, Falsification). If is_known_bug=True, MUST show source code is NOT patched.
        matched_url: List of relevant URLs (syzbot/CVE/patch links) if is_known_bug=True.
        extra_info: Additional context or suggestions.
        verification_details: Your explicit answers to the 4 self-check questions from Phase 4 (REQUIRED if is_known_bug=True).
    """
    return {
        "is_known_bug": is_known_bug,
        "evidence": evidence,
        "matched_url": matched_url,
        "extra_info": extra_info,
        "verification_details": verification_details
    }
    
def parse_search_results(results: KnownBugAnalysisResult):
    """Parse the search results and return a structured response."""
    return {
        "is_known_bug": results.is_known_bug,
        "evidence": results.evidence,
        "matched_url": results.matched_url,
        "extra_info": results.extra_info,
        "verification_details": results.verification_details
    }


def verify_result_quality(result: KnownBugAnalysisResult) -> tuple[bool, str]:
    """
    Verify if the result meets quality standards.
    Returns: (is_valid, reason)
    """
    # If claiming it's a known bug, must meet strict requirements
    if result.is_known_bug:
        if not result.matched_url or len(result.matched_url) == 0:
            return False, "No matched URLs provided for claimed known bug"

        valid_entity_url = False
        for u in result.matched_url:
            ul = u.lower()
            if any([
                "syzbot.org/bug?" in ul,
                "syzkaller.appspot.com/bug?id=" in ul,
                "github.com/torvalds/linux/commit/" in ul,
                ("git.kernel.org" in ul and ("/commit/" in ul or "/c/" in ul)),
                "nvd.nist.gov/vuln/detail/cve-" in ul,
                ("cve.mitre.org" in ul and "cvename.cgi?name=cve-" in ul),
            ]):
                valid_entity_url = True
                break

        if not valid_entity_url:
            return False, "Known bug claim lacks verifiable entity URLs (bug/commit/CVE links)"
        
        if not result.verification_details or len(result.verification_details) < 100:
            return False, "Verification details missing or too brief (need Phase 4 self-check answers)"
        
        # Check if evidence contains checkpoint scores
        if "Call Trace" not in result.evidence or "Symptom" not in result.evidence:
            return False, "Evidence must include 4-checkpoint verification (Call Trace, Symptom, Patch, Falsification)"
        
        # Must verify that source code is NOT patched
        evidence_lower = result.evidence.lower()
        verification_lower = result.verification_details.lower() if result.verification_details else ""
        
        has_source_check = any([
            "source code" in evidence_lower,
            "source" in verification_lower and "patch" in verification_lower,
            "vulnerable" in evidence_lower or "not patched" in evidence_lower,
            "absence of the fix" in evidence_lower,
            "fix is missing" in evidence_lower,
            "missing fix" in evidence_lower,
            "unpatched" in evidence_lower,
            "without the fix" in evidence_lower,
            "patch not present" in evidence_lower,
            "does not contain the patch" in evidence_lower,
            ("not patched" in verification_lower) or ("missing fix" in verification_lower)
        ])
        
        if not has_source_check:
            return False, "Must explicitly verify that source code is NOT patched (compare patch with current source)"
    else:
        # If claiming no match, must show sufficient search effort
        evidence_lower = result.evidence.lower()

        if "queries tried" not in evidence_lower:
            return False, "When reporting is_known_bug=False, evidence must include a 'Queries Tried' section"
        
        # Check if they tried multiple searches
        search_indicators = [
            "query" in evidence_lower or "search" in evidence_lower,
            "tried" in evidence_lower or "attempt" in evidence_lower,
            "0 results" in evidence_lower or "no results" in evidence_lower
        ]
        
        if not any(search_indicators):
            return False, "When reporting is_known_bug=False, must document search attempts (which queries tried, how many results)"
        
        # Warn if suspiciously few searches mentioned
        if evidence_lower.count("query") + evidence_lower.count("search") + evidence_lower.count("tried") < 3:
            return False, "Evidence suggests insufficient search attempts (need at least 8-10 diverse queries across 4 rounds)"

        has_syzbot_domain = ("syzbot.org" in evidence_lower) or ("syzkaller.appspot.com" in evidence_lower)
        if not has_syzbot_domain:
            return False, "No direct syzbot/syzkaller domain query evidence found"
    
    return True, "Result meets quality standards"


def create_search_reviewer_agent():
    """Create a reviewer agent to cross-check initial search decision semantically."""
    llm = get_model()
    reviewer_prompt = SEARCH_PROMPT + ENHANCE_PROMPT + """

You are a SECOND-PASS reviewer.
Your job is NOT to do fresh exhaustive search, but to verify whether the initial decision
is semantically justified by evidence quality.

Review rules:
1. Check if links are verifiable bug/commit/CVE entities.
2. Check if call-trace/symptom statements are consistent with linked evidence.
3. Check if patch-presence (patched/unpatched) verification is explicit when is_known_bug=True.
4. Keep binary output and list missing checks if any.
"""

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
    
    tools = SEARCH_AGENT_TOOLS

    agent_graph = create_agent(
        model=llm,
        tools=tools,
        middleware=build_shell_middleware(),
        system_prompt=SEARCH_PROMPT + ENHANCE_PROMPT,
        response_format=KnownBugAnalysisResult,
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
    
    for attempt in range(max_retries + 1):
        initial_input = {"messages": [HumanMessage(content=ANALYSIS_MESSAGE + COT_PROMPT)]}
        
        if attempt > 0:
            # Add retry context
            retry_message = f"""
RETRY ATTEMPT {attempt}/{max_retries}

Your previous result did not meet quality standards. Please:
1. Be MORE THOROUGH in your verification (Phase 3)
2. Complete the FULL self-check in Phase 4 with explicit checkpoint scores
3. If claiming a match (is_known_bug=True), you MUST:
   - Compare call trace structure
   - Check if SYMPTOMS match the patch DESCRIPTION (you don't need to analyze root cause deeply)
   - Verify the source code is NOT patched (compare patch with current source)
   - Provide verification_details showing you checked the source code
   - Include all 4 checkpoint scores in evidence
4. Make a BINARY decision: True or False. If uncertain, choose False.

Previous issue: {retry_reason}
"""
            initial_input["messages"].append(HumanMessage(content=retry_message))
        
        result = agent.invoke(
            initial_input, 
            config={"callbacks": [langfuse_handler], "recursion_limit": MAX_RECURSION_DEPTH}
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
                    print(f"[Search Agent] Max retries reached. Downgrading to 'unknown bug' due to insufficient verification.")
                    structured_result.is_known_bug = False
                    structured_result.evidence = f"INSUFFICIENT VERIFICATION: {structured_result.evidence}"
                    structured_result.extra_info = f"Quality check failed: {reason}"
                return structured_result

        # Second-pass semantic review for stability (workflow-based, no regex shortcuts)
        review_prompt = f"""
Please review the initial decision below and decide whether it is semantically justified.

Initial decision:
- is_known_bug: {structured_result.is_known_bug}
- matched_url: {structured_result.matched_url}
- evidence: {structured_result.evidence}
- verification_details: {structured_result.verification_details}
"""

        review_result = reviewer.invoke(
            {"messages": [HumanMessage(content=review_prompt + COT_PROMPT)]},
            config={"callbacks": [langfuse_handler], "recursion_limit": MAX_RECURSION_DEPTH}
        )

        if "structured_response" in review_result:
            review_struct = review_result["structured_response"]
            reviewer_disagree = (
                (not review_struct.agree_with_initial) or
                (review_struct.final_is_known_bug != structured_result.is_known_bug)
            )

            if reviewer_disagree:
                review_reason = review_struct.review_reason
                missing = ", ".join(review_struct.missing_checks) if review_struct.missing_checks else "none"
                print(f"[Search Agent] Attempt {attempt + 1} reviewer disagreement: {review_reason}; missing_checks={missing}")
                if attempt < max_retries:
                    retry_reason = f"Reviewer disagreement: {review_reason}; missing_checks={missing}"
                    continue

                # Conservative fallback after retries: prefer unknown instead of false known-bug claim
                if structured_result.is_known_bug and not review_struct.final_is_known_bug:
                    structured_result.is_known_bug = False
                    structured_result.evidence = f"INSUFFICIENT VERIFICATION (reviewer disagreement): {structured_result.evidence}"
                    structured_result.extra_info = f"Reviewer disagreement: {review_reason}; missing_checks={missing}"
                else:
                    structured_result.extra_info = (structured_result.extra_info or "") + f" | Reviewer: {review_reason}; missing_checks={missing}"
                return structured_result

        return structured_result
    
    return None
