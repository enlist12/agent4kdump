import build

from .prompt import *
from agent_core.model import get_model,MAX_RECURSION_DEPTH
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from typing import Optional, List
from pydantic import BaseModel, Field
from agent_core.tools import CUSTOM_AGENT_TOOLS, CODEQUERY_TOOLS
from agent_core.tools.commandTools import build_shell_middleware
from langfuse.langchain import CallbackHandler

SEARCH_AGENT_TOOLS = list(CUSTOM_AGENT_TOOLS.values()) + list(CODEQUERY_TOOLS.values())

ANALYSIS_MESSAGE = """
Start analysis. Determine if this crash is a known bug (CVE/Syzbot).
"""

class KnownBugAnalysisResult(BaseModel):
    """The final result determining if the crash is a known bug."""
    is_known_bug: bool = Field(description="True if the crash matches a known CVE or Syzbot bug, False otherwise. BINARY decision only - no ambiguity.")
    evidence: str = Field(description="The evidence supporting the conclusion. MUST include your 4-checkpoint verification scores if is_known_bug=True")
    matched_url: Optional[List[str]] = Field(description="The matched CVE URLs or Syzbot URLs or other relevant URLs if is_known_bug is True")
    extra_info: Optional[str] = Field(description="Any additional information or context")
    verification_details: Optional[str] = Field(description="Your explicit self-check answers from Phase 4 (REQUIRED if is_known_bug=True)")

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
        is_known_bug: True if match found (score ≥30/40 AND root cause match AND source is vulnerable), False otherwise. BINARY decision required.
        evidence: Complete explanation with 4-checkpoint scores. If is_known_bug=True, MUST show source code is NOT patched.
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
        
        if not result.verification_details or len(result.verification_details) < 100:
            return False, "Verification details missing or too brief (need Phase 4 self-check answers)"
        
        # Check if evidence contains checkpoint scores
        if "Call Trace" not in result.evidence or "Root Cause" not in result.evidence:
            return False, "Evidence must include 4-checkpoint verification scores"
        
        # Must verify that source code is NOT patched
        evidence_lower = result.evidence.lower()
        verification_lower = result.verification_details.lower() if result.verification_details else ""
        
        has_source_check = any([
            "source code" in evidence_lower,
            "source" in verification_lower and "patch" in verification_lower,
            "vulnerable" in evidence_lower or "not patched" in evidence_lower
        ])
        
        if not has_source_check:
            return False, "Must explicitly verify that source code is NOT patched (compare patch with current source)"
    
    return True, "Result meets quality standards"


def create_search_agent():
    """Create the search agent with configured tools and prompts."""
    llm = get_model()
    
    tools = SEARCH_AGENT_TOOLS

    agent_graph = create_agent(
        model=llm,
        tools=tools,
        middleware=build_shell_middleware(),
        system_prompt=TEST_PROMPT,
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
        
        if is_valid:
            return structured_result
        else:
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
    
    return None