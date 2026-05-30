import re
from typing import Annotated, Any, Callable, Dict, Literal, Optional, TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AnyMessage, HumanMessage
from langfuse.langchain import CallbackHandler
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import Command

from agents.utils.model import get_model
from runtime_config import get_invoke_config
from agents.tools import CODEQUERY_TOOLS, CUSTOM_AGENT_TOOLS
from agents.tools.commandTools import build_shell_middleware

from .prompt import (
    ANALYSIS_PROMPT,
    OBJECT_ANALYSIS_PROMPT,
    ROOT_CAUSE_ANALYSIS_PROMPT,
    TAINT_ANALYSIS_PROMPT,
)
from .schemas import RootCauseAnalysisResult, TaintAnalysisObj, TaintStepResult
from .taint_tree import MessageMemory, TaintTree, TaintTreeNode, TaintTreeRunner

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
        on_stage: Optional[Callable[[str, str], None]] = None,
    ) -> None:
        self.max_retries = max_retries
        self.max_taint_steps = max_taint_steps
        self.max_tree_nodes = max_tree_nodes
        self.max_branch_depth = max_branch_depth
        self.rag_context = rag_context
        self.on_stage = on_stage
        self.callback = CallbackHandler()
        self._final_result: Optional[RootCauseAnalysisResult] = None
        self._last_crash_report: str = ""
        self._last_trace: Dict[str, Any] = {}
        tools = list(CUSTOM_AGENT_TOOLS.values()) + list(CODEQUERY_TOOLS.values())
        middleware = build_shell_middleware()
        model = get_model()
        self.object_agent = create_agent(
            model=model,
            tools=tools,
            middleware=middleware,
            system_prompt=OBJECT_ANALYSIS_PROMPT.system,
            response_format=TaintAnalysisObj,
        )
        self.taint_agent = create_agent(
            model=model,
            tools=tools,
            middleware=middleware,
            system_prompt=TAINT_ANALYSIS_PROMPT.system,
            response_format=TaintStepResult,
        )
        self.root_agent = create_agent(
            model=model,
            tools=tools,
            middleware=middleware,
            system_prompt=ROOT_CAUSE_ANALYSIS_PROMPT.system,
            response_format=RootCauseAnalysisResult,
        )

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
            },
            get_invoke_config(),
        )
        messages = final_state.get("messages", [])
        taint_objects = final_state.get("taint_object", [])
        tool_calls: list[Dict[str, Any]] = []
        for msg in messages:
            msg_tool_calls = getattr(msg, "tool_calls", None)
            if not msg_tool_calls:
                continue
            for call in msg_tool_calls:
                tool_calls.append(
                    {
                        "name": call.get("name", ""),
                        "args": call.get("args", {}),
                    }
                )
        self._last_trace = {
            "crash_report": self._last_crash_report,
            "taint_chain": [item.model_dump() for item in taint_objects],
            "tool_calls": tool_calls,
            "last_node": final_state.get("last_node", ""),
            "taint_tree_summary": final_state.get("taint_tree_summary", ""),
        }
        return self._final_result

    def get_last_analysis_trace(self) -> Dict[str, Any]:
        """Return lightweight trace artifacts from the latest analysis run."""
        return dict(self._last_trace)

    def _node_start_debug(self, state: State) -> Command[Literal["object_analysis"]]:
        from agents.tools.gdbTools import getCrashReport

        crash_report = str(getCrashReport.invoke({}))
        self._last_crash_report = crash_report

        rag_context = (
            self.rag_context.strip() if self.rag_context and self.rag_context.strip() else ""
        )
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
                content=ANALYSIS_PROMPT.render(
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
            OBJECT_ANALYSIS_PROMPT.input(),
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
        if next_node == "taint_analysis" and self.on_stage:
            self.on_stage("taint_analysis", "starting")
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

        runner = TaintTreeRunner(
            max_taint_steps=self.max_taint_steps,
            max_tree_nodes=self.max_tree_nodes,
            max_branch_depth=self.max_branch_depth,
            analyze_node=self._analyze_taint_node,
            build_warning=self._warning_message,
            prepare_next_obj=self._fixup_column,
            join_text=self._join,
        )
        primary_path, update_messages, tree_summary = runner.run(current, state["messages"])
        new_objects = primary_path[1:] if len(primary_path) > 1 else []
        if self.on_stage:
            self.on_stage("taint_analysis", "completed")
        return Command(
            goto="root_cause_analysis",
            update={
                "messages": update_messages,
                "taint_object": new_objects,
                "last_node": "taint_analysis",
                "taint_tree_summary": tree_summary,
            },
        )

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
        branch_text = (
            TAINT_ANALYSIS_PROMPT.branch(
                condition=node.branch.condition,
                assumption=node.branch.assumption,
                reason=node.branch.reason,
            )
            if node.branch
            else ""
        )
        prompt = TAINT_ANALYSIS_PROMPT.history(
            step=len(tree.path_objects(node.node_id)),
            current_context=current.get_prompt(),
            history_desc=tree.format_history(node.node_id),
            branch_text=branch_text,
        )
        return self._call_agent(
            self.taint_agent,
            messages,
            prompt,
        )

    def _node_root_cause_analysis(self, state: State) -> Command[Literal["__end__"]]:
        if self.on_stage:
            self.on_stage("root_cause", "starting")
        history = state.get("taint_object", [])
        tree_summary = state.get("taint_tree_summary", "")
        warnings: list[str] = []
        for message in state.get("messages", []):
            content = str(getattr(message, "content", ""))
            if content.startswith(WARNING_PREFIX):
                warnings.append(content[len(WARNING_PREFIX) :].strip())
        history_text = (
            "\n".join(f"Step {idx + 1}: {obj.get_prompt()}" for idx, obj in enumerate(history))
            or "No structured taint chain available."
        )
        if tree_summary:
            history_text = (
                self._join(
                    history_text,
                    f"## Taint Tree Summary\n{tree_summary}",
                )
                or history_text
            )
        root_result, delta_messages, warning = self._call_agent(
            self.root_agent,
            state["messages"],
            ROOT_CAUSE_ANALYSIS_PROMPT.input(
                crash_report=next(
                    (
                        str(getattr(message, "content", ""))
                        for message in state.get("messages", [])
                        if str(getattr(message, "content", "")).startswith(
                            "The kernel crash report is below."
                        )
                    ),
                    "Crash report was not preserved in message state.",
                ),
                history=history_text,
                warning_text="\n".join(f"- {item}" for item in warnings) or "- none",
            ),
        )
        update_messages = list(delta_messages)
        if warning:
            warning_text = f"root_cause_analysis: {warning}"
            warnings.append(warning_text)
            update_messages.append(self._warning_message("root_cause_analysis", warning))
        if root_result is None:
            raise RuntimeError(
                "root_cause_analysis did not return a structured RootCauseAnalysisResult"
            )

        workflow_note = self._join(
            " | ".join(warnings) if warnings else "",
            f"Taint chain length={len(history)}; terminal_end={history[-1].end if history else False}.",
        )
        if workflow_note:
            root_result.evidence.append(f"Workflow note: {workflow_note}")
        self._final_result = root_result
        if self.on_stage:
            self.on_stage("root_cause", "completed")
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
    ) -> tuple[Any, list[AnyMessage], str]:
        base_messages = list(messages)
        current = list(base_messages) + [HumanMessage(content=prompt)]
        result = agent.invoke(
            {"messages": current},
            config=get_invoke_config(callbacks=[self.callback]),
        )
        result_messages = result.get("messages", current)
        delta_messages = result_messages[len(base_messages) :]
        return result.get("structured_response"), delta_messages, ""

    @staticmethod
    def _warning_message(step: str, warning: str) -> HumanMessage:
        return HumanMessage(content=f"{WARNING_PREFIX} {step}: {warning}")

    @staticmethod
    def _join(*parts: str) -> Optional[str]:
        items = [part.strip() for part in parts if part and part.strip()]
        return " | ".join(items) if items else None

    @staticmethod
    def _fixup_column(obj: TaintAnalysisObj) -> None:
        from agents.tools.fileTools import read_file_by_line_number

        if obj.column is not None:
            return
        try:
            context = str(
                read_file_by_line_number.invoke(
                    {
                        "file_path": obj.file_name,
                        "line_number": obj.line,
                        "line_range": 0,
                    }
                )
            )
        except Exception:
            return
        if context.startswith("❌"):
            return

        line = next(
            (item[4:] for item in context.splitlines() if item.startswith(" => ")),
            context.strip(),
        )
        match = re.search(r"\b" + re.escape(obj.variable_name) + r"\b", line)
        if match:
            obj.column = len(line[: match.start()].encode("utf-16-le")) // 2 + 1
