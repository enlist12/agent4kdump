from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any

DEFAULT_RECURSION_LIMIT = 300

_RUNTIME_CONFIG: dict[str, Any] = {
    "recursion_limit": DEFAULT_RECURSION_LIMIT,
}
_LOCK = RLock()


def set_runtime_config(**values: Any) -> None:
    """Update process-wide non-secret runtime settings loaded from config.yaml/UI."""
    with _LOCK:
        for key, value in values.items():
            if value is None:
                continue
            if key == "recursion_limit":
                value = int(value)
                if value <= 0:
                    raise ValueError("recursion_limit must be greater than 0")
            _RUNTIME_CONFIG[key] = value


def get_runtime_config() -> dict[str, Any]:
    with _LOCK:
        return deepcopy(_RUNTIME_CONFIG)


def get_invoke_config(**overrides: Any) -> dict[str, Any]:
    config = get_runtime_config()
    for key, value in overrides.items():
        if value is None:
            continue
        if key == "callbacks":
            existing = list(config.get("callbacks") or [])
            config[key] = existing + list(value)
        elif key == "configurable" and isinstance(value, dict):
            existing = dict(config.get("configurable") or {})
            existing.update(value)
            config[key] = existing
        else:
            config[key] = value
    return config
