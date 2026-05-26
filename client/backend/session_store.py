from __future__ import annotations

import threading
from uuid import uuid4

from .schemas import (
    AnalysisConfigPayload,
    AnalysisEventPayload,
    AnalysisSessionPayload,
    CreateSessionRequest,
    SessionResultPayload,
    SessionStatus,
    utc_now,
)


class SessionStore:
    """Small in-memory store for v1 client sessions and event streams."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, AnalysisSessionPayload] = {}
        self._events: dict[str, list[AnalysisEventPayload]] = {}
        self._cancelled: set[str] = set()

    def list_sessions(self) -> list[AnalysisSessionPayload]:
        with self._lock:
            return sorted(
                self._sessions.values(),
                key=lambda item: item.created_at,
                reverse=True,
            )

    def create_session(self, request: CreateSessionRequest) -> AnalysisSessionPayload:
        session_id = f"sess_{uuid4().hex[:12]}"
        session = AnalysisSessionPayload(
            id=session_id,
            name=request.name or f"analysis_{session_id[-6:]}",
            status="created",
            config=request.config,
            created_at=utc_now(),
        )
        with self._lock:
            self._sessions[session_id] = session
            self._events[session_id] = []
        self.add_event(session_id, "session.created", payload={"name": session.name})
        return session

    def get_session(self, session_id: str) -> AnalysisSessionPayload | None:
        with self._lock:
            return self._sessions.get(session_id)

    def update_session(
        self,
        session_id: str,
        *,
        status: SessionStatus | None = None,
        error: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        results: SessionResultPayload | None = None,
        config: AnalysisConfigPayload | None = None,
    ) -> AnalysisSessionPayload:
        with self._lock:
            session = self._sessions[session_id]
            data = session.model_dump()
            if status is not None:
                data["status"] = status
            if error is not None:
                data["error"] = error
            if started_at is not None:
                data["started_at"] = started_at
            if finished_at is not None:
                data["finished_at"] = finished_at
            if results is not None:
                data["results"] = results
            if config is not None:
                data["config"] = config
            updated = AnalysisSessionPayload(**data)
            self._sessions[session_id] = updated
            return updated

    def add_event(
        self,
        session_id: str,
        event_type: str,
        *,
        stage: str | None = None,
        payload: dict | None = None,
    ) -> AnalysisEventPayload:
        event = AnalysisEventPayload(
            id=f"evt_{uuid4().hex[:12]}",
            session_id=session_id,
            type=event_type,
            stage=stage,
            timestamp=utc_now(),
            payload=payload or {},
        )
        with self._lock:
            self._events.setdefault(session_id, []).append(event)
        return event

    def events_since(self, session_id: str, offset: int) -> tuple[list[AnalysisEventPayload], int]:
        with self._lock:
            events = self._events.get(session_id, [])
            return events[offset:], len(events)

    def cancel(self, session_id: str) -> None:
        with self._lock:
            self._cancelled.add(session_id)

    def is_cancelled(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._cancelled

