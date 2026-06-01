from typing import Annotated, Dict, Any
from langchain.agents import create_agent
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.memory import MemorySaver
from agents.utils.model import get_model
from ..runtime_config import get_invoke_config
from .commandTools import build_shell_middleware
from .tool_timeout import timed_tool

MAX_AGENTS = 5
_SUB_AGENTS: Dict[int, Dict[str, Any]] = {}
_NEXT_AGENT_ID = 0

@timed_tool(timeout_seconds=30)
def manage_sub_agent(
    action: Annotated[str, "One of: create, list, remove"],
    agent_id: Annotated[int | None, "Existing sub-agent ID for remove actions"] = None,
    system_prompt: Annotated[str | None, "System prompt used when creating a sub-agent"] = None,
    name: Annotated[str, "Short name when creating a sub-agent"] = "Assistant",
) -> Annotated[str, "Result of the requested sub-agent management action"]:
    """
    Manage sub-agents.
    Use action='create' to create one, action='list' to inspect existing agents,
    or action='remove' to delete one by ID.
    """
    global _NEXT_AGENT_ID

    if action == "list":
        if not _SUB_AGENTS:
            return "No active sub-agents."
        report = f"Active Sub-Agents ({len(_SUB_AGENTS)}/{MAX_AGENTS}):\n"
        for aid, data in _SUB_AGENTS.items():
            report += f"- ID: {aid} | Name: {data['name']}\n"
        return report

    if action == "remove":
        if agent_id is None:
            return "Error: agent_id is required when action='remove'."
        if agent_id not in _SUB_AGENTS:
            return f"Error: Agent with ID {agent_id} not found."
        removed_name = _SUB_AGENTS[agent_id]["name"]
        del _SUB_AGENTS[agent_id]
        return f"Agent '{removed_name}' (ID: {agent_id}) has been removed."

    if action != "create":
        return f"Error: Unsupported action '{action}'. Use create, list, or remove."

    if system_prompt is None or not system_prompt.strip():
        return "Error: system_prompt is required when action='create'."
    if len(_SUB_AGENTS) >= MAX_AGENTS:
        return f"Error: Maximum number of agents ({MAX_AGENTS}) reached. Please remove an unused agent first."

    try:
        model = get_model()

        from agents.tools import CUSTOM_AGENT_TOOLS, CODEQUERY_TOOLS
        tools = list(CUSTOM_AGENT_TOOLS.values()) + list(CODEQUERY_TOOLS.values())

        memory = MemorySaver()

        agent = create_agent(
            model=model,
            tools=tools,
            system_prompt=SystemMessage(content=system_prompt),
            checkpointer=memory,
            middleware=build_shell_middleware()
        )
        
        agent_id = _NEXT_AGENT_ID
        _NEXT_AGENT_ID += 1
        
        _SUB_AGENTS[agent_id] = {
            "agent_runnable": agent,
            "name": name,
            "system_prompt": system_prompt
        }
        
        return f"Agent created successfully. ID: {agent_id}, Name: '{name}'."
        
    except Exception as e:
        return f"Error creating agent: {str(e)}"

def message_sub_agent(
    agent_id: Annotated[int, "The ID of the agent to chat with"],
    message: Annotated[str, "The message or instruction for the agent"]
) -> Annotated[str, "The response from the agent"]:
    """
    Send a message to a specific sub-agent and get the response.
    The agent uses a checkpointer to maintain conversation history automatically.
    """
    if agent_id not in _SUB_AGENTS:
        return f"Error: Agent with ID {agent_id} not found. Use manage_sub_agent with action='list' to see available agents."
        
    agent_data = _SUB_AGENTS[agent_id]
    agent = agent_data["agent_runnable"]
    name = agent_data["name"]
    
    try:
        response = agent.invoke(
            {"messages": [HumanMessage(content=message)]},
            config=get_invoke_config(
                configurable={"thread_id": str(agent_id)},
                callbacks=[CallbackHandler()],
            ),
        )

        if isinstance(response, dict) and "messages" in response:
            messages = response["messages"]
            if messages:
                last_message = messages[-1]

                if isinstance(last_message, AIMessage): 
                    return last_message.content
                else:
                    return f"Agent '{name}' did not return a valid text response (last message type: {type(last_message)})."
            else:
                 return f"Agent '{name}' returned empty messages."

        if hasattr(response, "content"):
             return response.content

        return f"Unexpected response format from Agent '{name}'."
        
    except Exception as e:
        return f"Error executing agent '{name}' (ID: {agent_id}): {str(e)}"
