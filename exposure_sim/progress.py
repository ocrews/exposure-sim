"""Where a player's progress is saved.

The app only talks to ProgressStore. v1 keeps progress in the signed session cookie (no
database, nothing to set up). Moving to a database later means writing one new subclass,
for example a SqliteStore, and passing it to create_app. Nothing else changes.
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Progress:
    answers: dict = field(default_factory=dict)   # stage id -> answer dict (drafts included)
    locked: list = field(default_factory=list)    # stage ids the player locked in, in order

    def is_locked(self, stage_id: str) -> bool:
        return stage_id in self.locked

    def lock(self, stage_id: str):
        if stage_id not in self.locked:
            self.locked.append(stage_id)

    def unlock_from(self, stage_ids_after: list[str]):
        """Unlock a stage and every stage after it (later stages build on earlier decisions)."""
        self.locked = [s for s in self.locked if s not in stage_ids_after]

    def to_dict(self) -> dict:
        return {"a": self.answers, "l": self.locked}

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Progress":
        raw = raw or {}
        return cls(answers=dict(raw.get("a", {})), locked=list(raw.get("l", [])))


class ProgressStore(ABC):
    @abstractmethod
    def load(self, scenario_id: str) -> Progress: ...

    @abstractmethod
    def save(self, scenario_id: str, progress: Progress) -> None: ...

    def reset(self, scenario_id: str) -> None:
        self.save(scenario_id, Progress())


class SessionStore(ProgressStore):
    """Progress lives in Flask's signed session cookie. Keys are kept short to stay under ~4 KB."""

    def __init__(self, session_getter):
        self._session = session_getter   # a callable, so the store works across requests

    def load(self, scenario_id):
        return Progress.from_dict(self._session().get("p", {}).get(scenario_id))

    def save(self, scenario_id, progress):
        session = self._session()
        data = dict(session.get("p", {}))
        data[scenario_id] = progress.to_dict()
        session["p"] = data


class MemoryStore(ProgressStore):
    """Server-side, in-process. Useful for tests or a single-user local run with big scenarios.

    The browser only carries a random id. Progress is lost when the server restarts.
    """

    def __init__(self, session_getter):
        self._session = session_getter
        self._data: dict[str, dict[str, dict]] = {}

    def _uid(self) -> str:
        session = self._session()
        if "uid" not in session:
            session["uid"] = uuid.uuid4().hex
        return session["uid"]

    def load(self, scenario_id):
        return Progress.from_dict(self._data.get(self._uid(), {}).get(scenario_id))

    def save(self, scenario_id, progress):
        self._data.setdefault(self._uid(), {})[scenario_id] = progress.to_dict()
