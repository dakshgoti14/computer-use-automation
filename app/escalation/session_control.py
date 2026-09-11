"""Session registry: tracks which surface sessions exist and who controls them.

Enforces the exclusive-control invariant required by the assignment: while a
session's owner is HUMAN, automation must not act on it, and two actors can
never hold control of the same session simultaneously.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.browser.surface import SessionOwner, SurfaceAdapter
from app.errors import ErrorCode, HardFailureError


@dataclass
class ManagedSession:
    session_id: str
    surface: SurfaceAdapter
    owner: SessionOwner = SessionOwner.AUTOMATION
    run_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


class SessionRegistry:
    """In-memory registry of live surface sessions.

    Deliberately not persisted to disk: sessions are tied to a live browser
    process, so restarting the API process invalidates them anyway. This
    matches the assignment's guidance against unnecessary infrastructure.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ManagedSession] = {}

    def register(self, surface: SurfaceAdapter, *, run_id: str | None = None) -> ManagedSession:
        managed = ManagedSession(session_id=surface.session.session_id, surface=surface, run_id=run_id)
        self._sessions[managed.session_id] = managed
        return managed

    def get(self, session_id: str) -> ManagedSession:
        if session_id not in self._sessions:
            raise HardFailureError(
                ErrorCode.UNSUPPORTED_ACTION, f"No managed session with id {session_id!r}"
            )
        return self._sessions[session_id]

    def list_sessions(self) -> list[ManagedSession]:
        return list(self._sessions.values())

    def require_automation_owns(self, session_id: str) -> ManagedSession:
        """Raise unless automation currently owns the session.

        Called before any automated action (agent loop step, replay step)
        touches a shared session, so a human holding control can never be
        silently overridden.
        """

        managed = self.get(session_id)
        if managed.owner != SessionOwner.AUTOMATION:
            raise HardFailureError(
                ErrorCode.SESSION_UNDER_HUMAN_CONTROL,
                f"Session {session_id} is currently under human control; "
                "automation must not act until it is resumed.",
            )
        return managed

    def transfer_to_human(self, session_id: str) -> ManagedSession:
        managed = self.get(session_id)
        if managed.owner == SessionOwner.HUMAN:
            raise HardFailureError(
                ErrorCode.SESSION_ALREADY_CONTROLLED,
                f"Session {session_id} is already under human control.",
            )
        managed.owner = SessionOwner.HUMAN
        managed.surface.session.owner = SessionOwner.HUMAN
        managed.updated_at = datetime.now(UTC).isoformat()
        return managed

    def resume_automation(self, session_id: str) -> ManagedSession:
        managed = self.get(session_id)
        managed.owner = SessionOwner.AUTOMATION
        managed.surface.session.owner = SessionOwner.AUTOMATION
        managed.updated_at = datetime.now(UTC).isoformat()
        return managed

    def close(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)
