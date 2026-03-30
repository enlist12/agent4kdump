import re
from typing import Any, Optional

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from langfuse.langchain import CallbackHandler

from agent_core.model import MAX_RECURSION_DEPTH, get_model
from agent_core.tools import CODEQUERY_TOOLS, CUSTOM_AGENT_TOOLS
from agent_core.tools.commandTools import build_shell_middleware

from .prompt import (
    ANALYSIS_MESSAGE,
    AGENT_INPUT_PROMPT,
    CRASH_REPORT_PROMPT,
    COT_PROMPT,
    INITIAL_RETRY_PROMPT,
    OBJECT_ANALYSIS_INPUT_PROMPT,
    OBJECT_ANALYSIS_WORKFLOW,
    RETRY_PROMPT,
    ROLE_DEFINE,
    ROOT_CAUSE_ANALYSIS_WORKFLOW,
    ROOT_CAUSE_INPUT_PROMPT,
    TAINT_ANALYSIS_EXPLAIN,
    TAINT_ANALYSIS_WORKFLOW,
    TAINT_HISTORY_PROMPT,
)
from .schemas import RootCauseAnalysisResult, TaintAnalysisObj


class AnalysisProcess:
    def __init__(self, max_retries: int = 2, max_taint_steps: int = 6) -> None:
        self.max_retries = max_retries
        self.max_taint_steps = max_taint_steps
        self.callback = CallbackHandler()
        self._build_agents()

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
            response_format=TaintAnalysisObj,
        )
        self.root_agent = create_agent(
            model=model,
            tools=tools,
            middleware=middleware,
            system_prompt=ROLE_DEFINE + ROOT_CAUSE_ANALYSIS_WORKFLOW,
            response_format=RootCauseAnalysisResult,
        )

    def run(self) -> Optional[RootCauseAnalysisResult]:
        return self._run_once(0, "")

    def _run_once(self, attempt: int, retry_reason: str) -> RootCauseAnalysisResult:
        crash_report = self._get_crash_report()
        initial_prompt = ANALYSIS_MESSAGE
        if attempt:
            initial_prompt = INITIAL_RETRY_PROMPT.substitute(
                analysis_message=ANALYSIS_MESSAGE,
                attempt=attempt,
                retry_reason=retry_reason,
            )
        messages = [
            HumanMessage(content=initial_prompt),
            HumanMessage(
                content=CRASH_REPORT_PROMPT.substitute(crash_report=crash_report)
            ),
        ]
        warnings: list[str] = []
        chain: list[TaintAnalysisObj] = []

        current, messages, warning = self._call_agent(
            self.object_agent,
            messages,
            OBJECT_ANALYSIS_INPUT_PROMPT.substitute(),
            TaintAnalysisObj,
        )
        if warning:
            warnings.append("object_analysis: " + warning)

        if current is not None:
            self._fixup_column(current)
            chain.append(current)

        while current and not current.end and len(chain) - 1 < self.max_taint_steps:
            history = "\n".join(
                f"Step {idx + 1}: {obj.get_prompt()}" for idx, obj in enumerate(chain)
            )
            next_obj, messages, warning = self._call_agent(
                self.taint_agent,
                messages,
                TAINT_HISTORY_PROMPT.substitute(
                    step=len(chain),
                    current_context=current.get_prompt(),
                    history_desc=history,
                ),
                TaintAnalysisObj,
            )
            if warning:
                warnings.append("taint_analysis: " + warning)
                break
            if next_obj is None:
                break

            self._fixup_column(next_obj)
            if next_obj.same_target(current):
                next_obj.end = True
                next_obj.explain = self._join(
                    next_obj.explain,
                    "Stop: tracing converged to the same object in consecutive steps.",
                )
            chain.append(next_obj)
            current = next_obj

        if current and not current.end and len(chain) - 1 >= self.max_taint_steps:
            warnings.append(
                f"Reached max_taint_steps={self.max_taint_steps} before a terminal taint source was proven."
            )

        root_result, _, warning = self._call_agent(
            self.root_agent,
            messages,
            ROOT_CAUSE_INPUT_PROMPT.substitute(
                crash_report=crash_report,
                history="\n".join(
                    f"Step {idx + 1}: {obj.get_prompt()}"
                    for idx, obj in enumerate(chain)
                )
                or "No structured taint chain available.",
                warning_text="\n".join(f"- {item}" for item in warnings) or "- none",
            ),
            RootCauseAnalysisResult,
        )
        if warning:
            warnings.append("root_cause_analysis: " + warning)
        if root_result is None:
            root_result = self._fallback_result(chain, warnings)

        root_result.uncertainty = self._join(
            root_result.uncertainty,
            " | ".join(warnings) if warnings else "",
            f"Taint chain length={len(chain)}; terminal_end={chain[-1].end if chain else False}.",
        )
        return root_result

    def _call_agent(
        self,
        agent: Any,
        messages: list,
        prompt: str,
        expected_type: type,
    ) -> tuple[Any, list, str]:
        reason = ""
        last_messages = messages
        for attempt in range(self.max_retries + 1):
            current = list(messages) + [
                HumanMessage(
                    content=AGENT_INPUT_PROMPT.substitute(
                        prompt=prompt,
                        cot_prompt=COT_PROMPT,
                    )
                )
            ]
            if attempt:
                current.append(
                    HumanMessage(
                        content=RETRY_PROMPT.substitute(
                            attempt=attempt,
                            max_retries=self.max_retries,
                            reason=reason,
                            cot_prompt=COT_PROMPT,
                        )
                    )
                )
            result = agent.invoke(
                {"messages": current},
                config={
                    "callbacks": [self.callback],
                    "recursion_limit": MAX_RECURSION_DEPTH,
                },
            )
            last_messages = result.get("messages", current) if isinstance(result, dict) else current
            structured = result.get("structured_response") if isinstance(result, dict) else None
            if isinstance(structured, expected_type):
                return structured, last_messages, ""
            reason = "No structured_response returned"
        return None, last_messages, reason or "No structured_response returned"

    @staticmethod
    def _join(*parts: str) -> Optional[str]:
        items = [part.strip() for part in parts if part and part.strip()]
        return " | ".join(items) if items else None

    @staticmethod
    def _fallback_result(
        chain: list[TaintAnalysisObj],
        warnings: list[str],
    ) -> RootCauseAnalysisResult:
        if chain:
            last = chain[-1]
            return RootCauseAnalysisResult(
                root_cause=(
                    "Automated synthesis did not fully complete, but the taint trace still points to "
                    f"`{last.variable_name}` as the latest grounded object tied to the crash."
                ),
                trigger_path=" -> ".join(
                    f"{obj.current_function}:{obj.variable_name}" for obj in chain
                ),
                evidence=[
                    "Crash report was retrieved from kdump-gdbserver for this run.",
                    f"Last traced object: {last.file_name}:{last.line} in {last.current_function} for `{last.variable_name}`.",
                    "Automated synthesis had to fall back because the root-cause step did not return a valid structured report.",
                ],
                fix_suggestion=(
                    "Inspect the last traced source location and add the smallest missing validation, "
                    "state check, or error-handling branch there."
                ),
                confidence="low",
                uncertainty=" | ".join(warnings) if warnings else "root synthesis fallback",
            )
        return RootCauseAnalysisResult(
            root_cause=(
                "Automated analysis did not produce a confident source-grounded root cause from the current crash context."
            ),
            trigger_path="Crash report was loaded, but object identification and taint tracing did not complete.",
            evidence=[
                "Crash report was retrieved from kdump-gdbserver for this run.",
                "No structured taint chain was produced.",
                "Automated synthesis had to fall back because the root-cause step did not return a valid structured report.",
            ],
            fix_suggestion=(
                "Re-run analysis with stronger source grounding, then inspect the crash site and first upstream assignment manually."
            ),
            confidence="low",
            uncertainty=" | ".join(warnings) if warnings else "analysis fallback",
        )

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
