import re
from typing import Annotated, Any, Dict, Literal, Optional, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AnyMessage, HumanMessage
from langfuse.langchain import CallbackHandler
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command

from agent_core.model import MAX_RECURSION_DEPTH, get_model
from agent_core.tools import CODEQUERY_TOOLS, CUSTOM_AGENT_TOOLS
from agent_core.tools.commandTools import build_shell_middleware

from .prompt import (
    AGENT_INPUT_PROMPT,
    ANALYSIS_MESSAGE,
    BRANCH_ASSUMPTION_PROMPT,
    COT_PROMPT,
    OBJECT_ANALYSIS_INPUT_PROMPT,
    OBJECT_ANALYSIS_WORKFLOW,
    ROLE_DEFINE,
    ROOT_CAUSE_ANALYSIS_WORKFLOW,
    ROOT_CAUSE_INPUT_PROMPT,
    TAINT_ANALYSIS_EXPLAIN,
    TAINT_ANALYSIS_WORKFLOW,
    TAINT_HISTORY_PROMPT,
)
from .schemas import RootCauseAnalysisResult, TaintAnalysisObj, TaintStepResult
from .taint_tree import MessageMemory, TaintTree, TaintTreeNode, TaintTreeRunner
# TODO: 鍒犳帀閭ｄ簺sb鐨勯潤鎬佹柟娉曞拰杩囧鐨刾rompt銆?

WARNING_PREFIX = "[workflow_warning]"


def add_taint_obj(taint1, taint2):
    return taint1 + taint2


class State(TypedDict):
    messages: Annotated[AnyMessage, add_messages]
    taint_object: Annotated[list[TaintAnalysisObj], add_taint_obj]
    last_node: str
    taint_tree_summary: str


class AnalysisProcess:
    def __init__(
        self,
        max_retries: int = 2,
        max_taint_steps: int = 6,
        max_tree_nodes: int = 32,
        max_branch_depth: int = 4,
        rag_context: Optional[str] = None,
    ) -> None:
        self.max_retries = max_retries
        self.max_taint_steps = max_taint_steps
        self.max_tree_nodes = max_tree_nodes
        self.max_branch_depth = max_branch_depth
        self.rag_context = rag_context
        self.callback = CallbackHandler()
        self._final_result: Optional[RootCauseAnalysisResult] = None
        self._last_crash_report: str = ""
        self._last_trace: Dict[str, Any] = {}
        self._build_agents()
        self._build_graph()

    def _build_agents(self) -> None:
        tools = list(CUSTOM_AGENT_TOOLS.values()) + list(CODEQUERY_TOOLS.values())
        middleware = build_shell_middleware()
        model = get_model()
        self.object_agent = create_agent(
            model=model,
            tools=tools,
            middleware=middleware,
            system_prompt=ROLE_DEFINE + OBJECT_ANALYSIS_WORKFLOW,
            response_format=TaintAnalysisObj,
        )
        self.taint_agent = create_agent(
            model=model,
            tools=tools,
            middleware=middleware,
            system_prompt=ROLE_DEFINE + TAINT_ANALYSIS_WORKFLOW + TAINT_ANALYSIS_EXPLAIN,
            response_format=TaintStepResult,
        )
        self.root_agent = create_agent(
            model=model,
            tools=tools,
            middleware=middleware,
            system_prompt=ROLE_DEFINE + ROOT_CAUSE_ANALYSIS_WORKFLOW,
            response_format=RootCauseAnalysisResult,
        )

    def _build_graph(self) -> None:
        graph_builder = StateGraph(State)
        graph_builder.add_node("start_debug", self._node_start_debug)
        graph_builder.add_node("object_analysis", self._node_object_analysis)
        graph_builder.add_node("taint_analysis", self._node_taint_analysis)
        graph_builder.add_node("root_cause_analysis", self._node_root_cause_analysis)
        graph_builder.add_edge(START, "start_debug")
        self._graph = graph_builder.compile()

    def run(self) -> Optional[RootCauseAnalysisResult]:
        self._final_result = None
        final_state = self._graph.invoke(
            {
                "messages": [],
                "taint_object": [],
                "last_node": "",
                "taint_tree_summary": "",
            }
        )
        if isinstance(final_state, dict):
            self._last_trace = self._build_trace(final_state)
        return self._final_result

    def get_last_analysis_trace(self) -> Dict[str, Any]:
        """Return lightweight trace artifacts from the latest analysis run."""
        return dict(self._last_trace)

    def _node_start_debug(self, state: State) -> Command[Literal["object_analysis"]]:
        crash_report = self._get_crash_report()
        self._last_crash_report = crash_report
        
        rag_context = self.rag_context.strip() if self.rag_context and self.rag_context.strip() else ""
        rag_section = (
            "\nAdditional RAG context is provided below.\n"
            "Treat it as auxiliary hints, not ground truth.\n"
            "You must still verify conclusions from crash report + source evidence.\n"
            "If you reuse an idea from historical experience, explicitly separate it from facts proven in the current source trace.\n\n"
            f"{rag_context}\n"
            if rag_context
            else ""
        )
        initial_messages = [
            HumanMessage(
                content=ANALYSIS_MESSAGE.substitute(
                    crash_report=crash_report,
                    rag_context=rag_section,
                )
            ),
        ]
        return Command(
            goto="object_analysis",
            update={
                "messages": initial_messages,
                "last_node": "start_debug",
            },
        )

    def _node_object_analysis(
        self, state: State
    ) -> Command[Literal["taint_analysis", "root_cause_analysis"]]:
        taint_obj, delta_messages, warning = self._call_agent(
            self.object_agent,
            state["messages"],
            OBJECT_ANALYSIS_INPUT_PROMPT.substitute(),
            TaintAnalysisObj,
        )
        update_messages = list(delta_messages)
        if warning:
            update_messages.append(self._warning_message("object_analysis", warning))
        update: dict[str, Any] = {
            "messages": update_messages,
            "last_node": "object_analysis",
        }
        if taint_obj is None:
            return Command(goto="root_cause_analysis", update=update)

        self._fixup_column(taint_obj)
        update["taint_object"] = [taint_obj]
        next_node = "root_cause_analysis" if taint_obj.end else "taint_analysis"
        return Command(goto=next_node, update=update)

    def _node_taint_analysis(
        self, state: State
    ) -> Command[Literal["taint_analysis", "root_cause_analysis"]]:
        history = state.get("taint_object", [])
        if not history:
            return Command(
                goto="root_cause_analysis",
                update={"last_node": "taint_analysis"},
            )

        current = history[-1]
        if current.end:
            return Command(
                goto="root_cause_analysis",
                update={"last_node": "taint_analysis"},
            )

        primary_path, update_messages, tree_summary = self._run_taint_tree(
            current,
            state["messages"],
        )
        new_objects = primary_path[1:] if len(primary_path) > 1 else []
        return Command(
            goto="root_cause_analysis",
            update={
                "messages": update_messages,
                "taint_object": new_objects,
                "last_node": "taint_analysis",
                "taint_tree_summary": tree_summary,
            },
        )

    def _run_taint_tree(
        self,
        root_obj: TaintAnalysisObj,
        messages: list[AnyMessage],
    ) -> tuple[list[TaintAnalysisObj], list[AnyMessage], str]:
        runner = TaintTreeRunner(
            max_taint_steps=self.max_taint_steps,
            max_tree_nodes=self.max_tree_nodes,
            max_branch_depth=self.max_branch_depth,
            analyze_node=self._analyze_taint_node,
            build_warning=self._warning_message,
            build_branch_message=lambda branch: HumanMessage(
                content=self._branch_prompt_text(branch)
            ),
            prepare_next_obj=self._fixup_column,
            join_text=self._join,
        )
        return runner.run(root_obj, messages)

    def _analyze_taint_node(
        self,
        tree: TaintTree,
        memory: MessageMemory,
        node: TaintTreeNode,
    ) -> tuple[Optional[TaintStepResult], list[AnyMessage], str]:
        """Analyze one taint-tree node with the taint agent."""
        messages = memory.restore(node.checkpoint_id)
        current = node.taint_obj
        if current is None:
            return None, [], "Missing taint object"
        prompt = TAINT_HISTORY_PROMPT.substitute(
            step=len(tree.path_objects(node.node_id)),
            current_context=current.get_prompt(),
            history_desc=tree.format_history(node.node_id),
        )
        if node.branch:
            prompt = self._branch_prompt_text(node.branch) + "\n\n" + prompt
        return self._call_agent(
            self.taint_agent,
            messages,
            prompt,
            TaintStepResult,
        )

    @staticmethod
    def _branch_prompt_text(branch) -> str:
        """Build the prompt text for a branch assumption."""
        return BRANCH_ASSUMPTION_PROMPT.substitute(
            condition=branch.condition,
            assumption=branch.assumption,
            reason=branch.reason,
        )

    def _node_root_cause_analysis(self, state: State) -> Command[Literal["__end__"]]:
        history = state.get("taint_object", [])
        tree_summary = state.get("taint_tree_summary", "")
        warnings = self._collect_warnings(state.get("messages", []))
        history_text = "\n".join(
            f"Step {idx + 1}: {obj.get_prompt()}"
            for idx, obj in enumerate(history)
        ) or "No structured taint chain available."
        if tree_summary:
            history_text = self._join(
                history_text,
                f"## Taint Tree Summary\n{tree_summary}",
            ) or history_text
        root_result, delta_messages, warning = self._call_agent(
            self.root_agent,
            state["messages"],
            ROOT_CAUSE_INPUT_PROMPT.substitute(
                crash_report=self._extract_crash_report(state.get("messages", [])),
                history=history_text,
                warning_text="\n".join(f"- {item}" for item in warnings) or "- none",
            ),
            RootCauseAnalysisResult,
        )
        update_messages = list(delta_messages)
        if warning:
            warning_text = f"root_cause_analysis: {warning}"
            warnings.append(warning_text)
            update_messages.append(
                self._warning_message("root_cause_analysis", warning)
            )
        if root_result is None:
            raise RuntimeError(
                "root_cause_analysis did not return a structured RootCauseAnalysisResult"
            )

        root_result.uncertainty = self._join(
            root_result.uncertainty,
            " | ".join(warnings) if warnings else "",
            f"Taint chain length={len(history)}; terminal_end={history[-1].end if history else False}.",
        )
        self._final_result = root_result
        return Command(
            goto=END,
            update={
                "messages": update_messages,
                "last_node": "root_cause_analysis",
            },
        )

    def _call_agent(
        self,
        agent: Any,
        messages: list[AnyMessage],
        prompt: str,
        expected_type: type,
    ) -> tuple[Any, list[AnyMessage], str]:
        base_messages = list(messages)
        current = list(base_messages) + [
            HumanMessage(
                content=AGENT_INPUT_PROMPT.substitute(
                    prompt=prompt,
                    cot_prompt=COT_PROMPT,
                )
            )
        ]
        result = agent.invoke(
            {"messages": current},
            config={
                "callbacks": [self.callback],
                "recursion_limit": MAX_RECURSION_DEPTH,
            },
        )
        result_messages = result.get("messages", current) if isinstance(result, dict) else current
        if isinstance(result_messages, list):
            delta_messages = result_messages[len(base_messages) :]
        else:
            delta_messages = current[len(base_messages) :]
        structured = result.get("structured_response") if isinstance(result, dict) else None
        if isinstance(structured, expected_type):
            return structured, delta_messages, ""
        if expected_type is TaintStepResult and isinstance(structured, TaintAnalysisObj):
            if structured.end:
                return (
                    TaintStepResult(
                        kind="terminal",
                        terminal_reason=structured.explain,
                    ),
                    delta_messages,
                    "",
                )
            return (
                TaintStepResult(kind="single", next_obj=structured),
                delta_messages,
                "",
            )
        return None, delta_messages, "No structured_response returned"

    @staticmethod
    def _warning_message(step: str, warning: str) -> HumanMessage:
        return HumanMessage(content=f"{WARNING_PREFIX} {step}: {warning}")

    @staticmethod
    def _collect_warnings(messages: list[AnyMessage]) -> list[str]:
        warnings: list[str] = []
        for message in messages:
            content = getattr(message, "content", "")
            if isinstance(content, str) and content.startswith(WARNING_PREFIX):
                warnings.append(content[len(WARNING_PREFIX) :].strip())
        return warnings

    @staticmethod
    def _extract_crash_report(messages: list[AnyMessage]) -> str:
        for message in messages:
            content = getattr(message, "content", "")
            if isinstance(content, str) and content.startswith(
                "The kernel crash report is below."
            ):
                return content
        return "Crash report was not preserved in message state."

    @staticmethod
    def _join(*parts: str) -> Optional[str]:
        items = [part.strip() for part in parts if part and part.strip()]
        return " | ".join(items) if items else None

    @staticmethod
    def _get_crash_report() -> str:
        from agent_core.tools.gdbTools import getCrashReport

        report = getCrashReport.invoke({})
        return report if isinstance(report, str) else str(report)

    @staticmethod
    def _fixup_column(obj: TaintAnalysisObj) -> None:
        from agent_core.tools.fileTools import read_file_by_line_number

        if obj.column is not None:
            return
        try:
            context = read_file_by_line_number.invoke(
                {"file_path": obj.file_name, "line_number": obj.line, "line_range": 0}
            )
        except Exception:
            return
        if not isinstance(context, str) or context.startswith("❌"):
            return

        line = next(
            (item[4:] for item in context.splitlines() if item.startswith(" => ")),
            context.strip(),
        )
        match = re.search(r"\b" + re.escape(obj.variable_name) + r"\b", line)
        if match:
            obj.column = len(line[: match.start()].encode("utf-16-le")) // 2 + 1

    def _build_trace(self, final_state: Dict[str, Any]) -> Dict[str, Any]:
        """Collect taint-chain and tool-call metadata for experience persistence."""
        messages = final_state.get("messages", []) if isinstance(final_state, dict) else []
        taint_objects = final_state.get("taint_object", []) if isinstance(final_state, dict) else []
        tool_calls: list[Dict[str, Any]] = []

        for msg in messages:
            msg_tool_calls = getattr(msg, "tool_calls", None)
            if not msg_tool_calls:
                continue
            for call in msg_tool_calls:
                if isinstance(call, dict):
                    tool_calls.append(
                        {
                            "name": call.get("name", ""),
                            "args": call.get("args", {}),
                        }
                    )

        taint_chain = []
        for item in taint_objects:
            if isinstance(item, TaintAnalysisObj):
                taint_chain.append(item.model_dump())

        return {
            "crash_report": self._last_crash_report,
            "taint_chain": taint_chain,
            "tool_calls": tool_calls,
            "last_node": final_state.get("last_node", "") if isinstance(final_state, dict) else "",
            "taint_tree_summary": final_state.get("taint_tree_summary", "")
            if isinstance(final_state, dict)
            else "",
        }
