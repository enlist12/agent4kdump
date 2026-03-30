from .analysis_process import AnalysisProcess
from .schemas import RootCauseAnalysisResult


def parse_analyze_results(result: RootCauseAnalysisResult) -> dict:
    """Compatibility wrapper for existing callers."""
    return result.model_dump()


def runAnalyzeAgent(max_retries: int = 2, max_taint_steps: int = 6):
    """
    Run the source-style stateful analysis workflow.

    Args:
        max_retries: Retries for structured-step failures and final quality gate.
        max_taint_steps: Upper bound of reverse-taint hops before forced finalization.
    """
    process = AnalysisProcess(
        max_retries=max_retries,
        max_taint_steps=max_taint_steps,
    )
    return process.run()
