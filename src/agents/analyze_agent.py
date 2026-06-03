from .analysis_process import AnalysisProcess
from .schemas import RootCauseAnalysisResult
from typing import Callable, Optional


def runAnalyzeAgent(
    max_retries: int = 2,
    max_taint_steps: int = 6,
    rag_context: Optional[str] = None,
    return_trace: bool = False,
    on_stage: Optional[Callable[[str, str], None]] = None,
):
    """
    Run the source-style stateful analysis workflow.

    Args:
        max_retries: Retries for structured-step failures and final quality gate.
        max_taint_steps: Upper bound of reverse-taint hops before forced finalization.
        rag_context: Optional RAG briefing injected before analysis begins.
        return_trace: Whether to return internal analysis trace for experience persistence.
        on_stage: Optional callback for stage transitions (stage_name, status).
    """
    process = AnalysisProcess(
        max_retries=max_retries,
        max_taint_steps=max_taint_steps,
        rag_context=rag_context,
        on_stage=on_stage,
    )
    result = process.run()
    if return_trace:
        return result, process.get_last_analysis_trace()
    return result
