import signal
import threading
import time
from functools import wraps
from queue import Queue
from typing import Any, Callable, Optional

from langchain_core.tools import tool


class ToolTimeoutError(BaseException):
    """Raised when a tool execution exceeds the configured timeout."""


def _run_in_daemon_thread(
    func: Callable[..., Any],
    timeout_seconds: int,
    *args: Any,
    **kwargs: Any,
) -> Any:
    result_queue: Queue = Queue(maxsize=1)

    def target() -> None:
        try:
            result_queue.put(("result", func(*args, **kwargs)))
        except BaseException as exc:  # noqa: BLE001
            result_queue.put(("error", exc))

    worker = threading.Thread(target=target, daemon=True)
    worker.start()
    worker.join(timeout_seconds)
    if worker.is_alive():
        raise ToolTimeoutError(f"tool execution exceeded {timeout_seconds} seconds")

    status, payload = result_queue.get()
    if status == "error":
        raise payload
    return payload


def run_with_timeout(
    func: Callable[..., Any],
    timeout_seconds: int,
    *args: Any,
    **kwargs: Any,
) -> Any:
    if timeout_seconds <= 0:
        return func(*args, **kwargs)

    if threading.current_thread() is not threading.main_thread():
        return _run_in_daemon_thread(func, timeout_seconds, *args, **kwargs)

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_delay, previous_interval = signal.getitimer(signal.ITIMER_REAL)
    start_time = time.monotonic()

    def _handle_timeout(signum: int, frame: Any) -> None:  # noqa: ARG001
        raise ToolTimeoutError(f"tool execution exceeded {timeout_seconds} seconds")

    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return func(*args, **kwargs)
    finally:
        elapsed = time.monotonic() - start_time
        restored_delay = max(previous_delay - elapsed, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)
        signal.setitimer(signal.ITIMER_REAL, restored_delay, previous_interval)


def default_timeout_message(tool_name: str, timeout_seconds: int) -> str:
    return f"Error: tool '{tool_name}' timed out after {timeout_seconds} seconds."


def timed_tool(
    *,
    timeout_seconds: int,
    timeout_factory: Optional[Callable[[str, int], Any]] = None,
) -> Callable[[Callable[..., Any]], Any]:
    """Decorate a LangChain tool with a uniform timeout guard."""

    def decorator(func: Callable[..., Any]) -> Any:
        factory = timeout_factory or default_timeout_message

        @wraps(func)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            try:
                return run_with_timeout(func, timeout_seconds, *args, **kwargs)
            except ToolTimeoutError:
                return factory(func.__name__, timeout_seconds)

        return tool(wrapped)

    return decorator
