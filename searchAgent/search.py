from .prompt import *
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))) 
from agent_core.model import get_model,MAX_RECURSION_DEPTH
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from typing import Optional
from pydantic import BaseModel, Field
from agent_core.agent_tools import CUSTOM_AGENT_TOOLS, CODEQUERY_TOOLS
from langfuse.langchain import CallbackHandler

SEARCH_AGENT_TOOLS = list(CUSTOM_AGENT_TOOLS.values()) + list(CODEQUERY_TOOLS.values())

class KnownBugAnalysisResult(BaseModel):
    """The final result determining if the crash is a known bug."""
    is_known_bug: bool = Field(description="True if the crash matches a known CVE or Syzbot bug or designed deliberately, False otherwise")
    evidence: str = Field(description="The evidence supporting the conclusion (e.g., matched stack trace, CVE ID, Syzbot ID, patch analysis)")
    matched_url: Optional[str] = Field(description="The matched CVE URL or Syzbot URL or other relevant URL if is_known_bug is True")
    extra_info: Optional[str] = Field(description="Any additional information or tools that you need")

@tool
def submit_known_bug_analysis(
    is_known_bug: bool,
    evidence: str,
    matched_url: Optional[str] = None,
    extra_info: Optional[str] = None
):
    """
    Submit the final analysis result.
    Call this tool ONLY when you have determined whether the crash is a known bug or not.
    
    Args:
        is_known_bug: Set to True if you found a matching CVE or Syzbot report.
        evidence: Explain WHY you think it matches (or why it doesn't). Include stack trace comparison, variable analysis, etc.
        confidence_score: How sure are you? (0.0 - 1.0)
        matched_id: The ID of the known bug (e.g., "CVE-2023-1234" or "syzbot-12345").
    """
    return {
        "is_known_bug": is_known_bug,
        "evidence": evidence,
        "matched_url": matched_url,
        "extra_info": extra_info
    }
    
def parse_search_results(results:KnownBugAnalysisResult):
    """Parse the search results and return a structured response."""
    return {
        "is_known_bug": results.is_known_bug,
        "evidence": results.evidence,
        "matched_url": results.matched_url,
        "extra_info": results.extra_info
    }
    

def createSearchAgent(model_name="openai", api_key=None, provider=None):
    llm = get_model(provider_name=model_name, key=api_key)
    
    tools = SEARCH_AGENT_TOOLS

    agent_graph = create_agent(
        model=llm,
        tools=tools,
        system_prompt=TEST_PROMPT,
        response_format=KnownBugAnalysisResult
    )
    
    return agent_graph

def runSearchAgent():
    agent = createSearchAgent(model_name="openai", api_key=None, provider=None)

    initial_input = {"messages": [HumanMessage(content="Start analysis. Determine if this crash is a known bug (CVE/Syzbot).")]}
    
    # Initialize Langfuse CallbackHandler
    langfuse_handler = CallbackHandler()

    result = agent.invoke(initial_input, config={"callbacks": [langfuse_handler], "recursion_limit": MAX_RECURSION_DEPTH})
    
    # Extract the structured response
    if "structured_response" in result:
        return result["structured_response"]
    
    return None