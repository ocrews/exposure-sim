"""The Stage contract. Every step of the game is a subclass of Stage.

This file uses the same pattern the player designs in the final stage: an abstract base
class defines the contract (parse_form + evaluate), shared helpers live on the base, and a
registry lets the app find stages without importing each one by name.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from exposure_sim.models import Scenario

STAGES: list["Stage"] = []


def register(cls: type["Stage"]) -> type["Stage"]:
    """Class decorator: instantiate the stage and add it to the ordered registry."""
    STAGES.append(cls())
    STAGES.sort(key=lambda s: s.order)
    return cls


def get_stage(stage_id: str) -> "Stage | None":
    return next((s for s in STAGES if s.id == stage_id), None)


@dataclass
class Note:
    kind: str   # good | miss | tip
    text: str


@dataclass
class Evaluation:
    score: int = 0
    max_score: int = 0
    notes: list[Note] = field(default_factory=list)
    pushback: list[str] = field(default_factory=list)   # Socratic questions shown before lock-in

    def award(self, points: int, max_points: int, good: str | None = None, miss: str | None = None):
        """Add a scored item. Full marks note `good`; anything less notes `miss`."""
        self.max_score += max_points
        self.score += max(0, min(points, max_points))
        if points >= max_points and good:
            self.notes.append(Note("good", good))
        elif points < max_points and miss:
            self.notes.append(Note("miss", miss))

    def tip(self, text: str):
        self.notes.append(Note("tip", text))

    def ask(self, question: str):
        self.pushback.append(question)

    @property
    def percent(self) -> int:
        return round(100 * self.score / self.max_score) if self.max_score else 0

    @property
    def strong(self) -> bool:
        return not self.pushback


class Stage(ABC):
    id: str = "base"
    order: int = 0
    title: str = ""
    goal: str = ""          # one line shown above the form
    template: str = ""      # partial under templates/stages/

    @abstractmethod
    def parse_form(self, form, scenario: Scenario) -> dict:
        """Turn submitted form fields into a small JSON-safe answer dict (stored in the session)."""

    @abstractmethod
    def evaluate(self, scenario: Scenario, answer: dict) -> Evaluation:
        """Grade an answer against the scenario. Must be deterministic: it is re-run on every view."""

    def context(self, scenario: Scenario, answer: dict) -> dict:
        """Extra template variables. Override when the form needs computed options."""
        return {}

    # ---- shared helpers for subclasses ------------------------------------------------
    @staticmethod
    def checked(form, name: str, allowed) -> list[str]:
        """Read a checkbox group, dropping anything not in the allowed set (never trust the form)."""
        allowed = set(allowed)
        return sorted({v for v in form.getlist(name) if v in allowed})

    @staticmethod
    def choice(form, name: str, allowed, default=None):
        value = form.get(name)
        return value if value in set(allowed) else default

    @staticmethod
    def names(items) -> str:
        items = list(items)
        if len(items) <= 1:
            return "".join(items)
        return ", ".join(items[:-1]) + " and " + items[-1]
