"""Prompt definitions for analysis agents."""

from string import Template

from agents.search_prompt import COT_PROMPT

ROLE_DEFINE = Template(
    """## Role Definition

You are a senior Linux kernel programmer debugging a crash from a kdump / gdb context.
The available tools can inspect crash state, read source code, find definitions, find references,
and query call relationships. Use them like a careful kernel engineer, not like a generic chatbot.

The search stage has already concluded that this crash is NOT a confirmed known bug.
Your job is to produce a source-grounded root-cause analysis for the current codebase.
"""
).substitute()

TAINT_ANALYSIS_EXPLAIN = Template(
    """## About Taint Analysis

The debugging process follows reverse taint analysis.
You must first identify the object that directly leads to the crash, then trace how its bad state
is introduced step by step until you reach the earliest source that can actually explain the crash.

Rules for taint tracing:
1. Each step traces exactly ONE upstream hop.
2. Prefer concrete source evidence over name similarity.
3. Each hop must stay grounded in file, function, and line.
4. If tracing reaches an external input boundary, config boundary, call boundary, global state boundary,
   or clearly converges on the same object again, mark `end=true`.
5. Do not skip directly to a final root cause during intermediate taint steps.
"""
).substitute()

OBJECT_ANALYSIS_WORKFLOW = Template(
    """## Your Task

In this node, identify the object that directly causes the crash.
Focus on the faulting statement, the invalid pointer/value/state at the crash site,
and the exact source location that should become the first taint object.

## Workflow

1. Read the crash report and identify the fault type, crash function, and faulting statement if visible.
2. Focus on the exact object whose invalid state makes the statement crash.
3. Use source-reading and call-chain tools as needed to pin the object to a concrete file, function, and line.
4. Explain why this object is the direct crash trigger.
5. Set `end=false` unless this object is already an obvious terminal boundary and no earlier source is meaningful.

## Output

Return exactly one structured `TaintAnalysisObj` with:
- `file_name`
- `variable_name`
- `line`
- `column` if known
- `current_function`
- `explain`
- `end`

## Notes

- Do not jump to the final root cause here.
- Skip generic wrapper frames and obvious noise.
- If line/column is uncertain, provide the best grounded location you can justify.
"""
).substitute()

TAINT_ANALYSIS_WORKFLOW = Template(
    """## Input

You will be given the current taint object and the history of previously traced objects.

## Your Task

Perform backward taint analysis for the current object.
Find the next upstream source that explains how the current object's bad state is produced.

## Workflow

1. Start from the current object's location and inspect its definition, assignments, callers, parameters, return values, fields, and relevant state transitions.
2. If there is one strongest upstream source, return it as `kind="single"` with `next_obj`.
3. If a conditional statement creates multiple meaningful paths, return `kind="branch"` with every branch assumption.
4. If you have reached a terminal boundary or tracing converges, return `kind="terminal"`.

## Output

Return exactly one structured `TaintStepResult`:
- `kind`: `single`, `branch`, or `terminal`
- `next_obj`: required only when `kind="single"`
- `branches`: required only when `kind="branch"`
- `terminal_reason`: required only when `kind="terminal"`

## Notes

- For `single`, one hop only. Never compress multiple upstream hops into one answer.
- Do not repeat a previously traced object unless you are explicitly marking convergence with `end=true`.
- If several candidates exist, choose the one with the best source grounding and explain the ambiguity briefly in `explain`.
- For `branch`, keep each branch small: condition, assumption, reason, and priority. Lower priority is analyzed first.
"""
).substitute()

ROOT_CAUSE_ANALYSIS_WORKFLOW = Template(
    """## Input

You will be given the crash report, the taint-analysis path, and any workflow warnings.

## Your Task

Summarize the complete analysis and provide the final root-cause report for this crash.
The report must stay grounded in the crash facts and the traced taint chain.

## Workflow

1. Read the crash report and the taint chain as one connected path.
2. Identify the earliest grounded source that explains the invalid object/state at the crash site.
3. Summarize the trigger path in execution order.
4. Extract concrete evidence items from crash facts and source locations.
5. Suggest the smallest plausible fix consistent with the traced logic.
6. If any step is not fully proven, keep confidence conservative and record it in `uncertainty`.

## Output

Return a structured `RootCauseAnalysisResult` with:
- `root_cause`
- `trigger_path`
- `evidence`
- `fix_suggestion`
- `confidence`
- `uncertainty`

## Notes

- Do not invent upstream facts that are not grounded in the crash report or source trace.
- At least one evidence item must contain explicit file/line grounding.
- If the taint chain is incomplete, say so directly in `uncertainty`.
"""
).substitute()

ANALYSIS_MESSAGE = Template(
    """Next, I will provide you with a parsed crash report.
The bug is already classified as NOT known by `search_agent`.
Based on the report, you need to debug the crash step by step and produce a source-grounded root-cause analysis.

Follow this workflow strictly:
1. start_debug
2. object_analysis
3. taint_analysis
4. root_cause_analysis
"""
).substitute()

RAG_CONTEXT_PROMPT = Template(
    """Additional RAG context is provided below.
Treat it as auxiliary hints, not ground truth.
You must still verify conclusions from crash report + source evidence.

$rag_context
"""
)

CRASH_REPORT_PROMPT = Template(
    """The kernel crash report is below.
Use it as the primary runtime grounding for this analysis.

$crash_report
"""
)

OBJECT_ANALYSIS_INPUT_PROMPT = Template(
    """## Current Node

object_analysis

Based on the crash report already provided, identify the immediate crash object.
Return exactly one structured `TaintAnalysisObj`.
Keep file, function, and line concrete.
Set `end=false` unless tracing is already complete at this first object.
"""
)

TAINT_HISTORY_PROMPT = Template(
    """You are performing taint analysis to find the root cause of a kernel crash.

We have already tainted the following objects. Do not choose them again unless tracing has converged and you are explicitly ending the chain:
$history_desc

Current step context:
$current_context

Current taint step: $step

Now, based on the crash report, previous taint steps, and source inspection:
1. If there is a new upstream object that should be tainted next, output `kind="single"` with one `next_obj`.
2. If a condition creates multiple meaningful static-analysis paths, output `kind="branch"` with branch assumptions.
3. If this path is already at the earliest meaningful boundary, output `kind="terminal"`.

Important:
- Do not skip across multiple hops.
- Prefer objects closer to the real origin of the bad state.
- Keep the result concrete: file, function, line, and explanation.
"""
)

BRANCH_ASSUMPTION_PROMPT = Template(
    """## Current Conditional Branch

Analyze only this conditional branch.

Condition: $condition
Assumption: $assumption
Reason: $reason

Do not import conclusions from sibling branches unless they are proven common source facts.
"""
)

ROOT_CAUSE_INPUT_PROMPT = Template(
    """Next is the taint-analysis path and related explanations.
Based on the full analysis, determine the root cause of the crash and provide a fix suggestion.
Use only the crash report, taint chain, and source-grounded observations.
If any chain segment is unproven, state it in `uncertainty` instead of asserting it.

## Crash Report
$crash_report

## Taint Chain
$history

## Workflow Warnings
$warning_text

## Required Output
1. `root_cause` must mention the fault type and invalid object/state.
2. `trigger_path` must be ordered and concise.
3. `evidence` must include crash-trace and source-level observations.
4. `fix_suggestion` must be minimal and actionable.
5. `confidence` must be `low`, `medium`, or `high`.
6. If the chain is incomplete, `uncertainty` must explain why.
"""
)

AGENT_INPUT_PROMPT = Template(
    """$prompt

$cot_prompt
"""
)

__all__ = [
    "COT_PROMPT",
    "ROLE_DEFINE",
    "TAINT_ANALYSIS_EXPLAIN",
    "OBJECT_ANALYSIS_WORKFLOW",
    "TAINT_ANALYSIS_WORKFLOW",
    "ROOT_CAUSE_ANALYSIS_WORKFLOW",
    "ANALYSIS_MESSAGE",
    "RAG_CONTEXT_PROMPT",
    "CRASH_REPORT_PROMPT",
    "OBJECT_ANALYSIS_INPUT_PROMPT",
    "TAINT_HISTORY_PROMPT",
    "BRANCH_ASSUMPTION_PROMPT",
    "ROOT_CAUSE_INPUT_PROMPT",
    "AGENT_INPUT_PROMPT",
]
