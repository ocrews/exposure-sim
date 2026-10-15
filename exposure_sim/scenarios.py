"""Load scenario JSON files into frozen Scenario objects and check they are internally consistent."""
from __future__ import annotations

import json
from pathlib import Path

from exposure_sim.models import (AssetGroup, Constraints, GradingRules, Scenario, Source, Team,
                                 TicketSystem, Zone)

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "data" / "scenarios"
CURRENT_SCHEMA = 1


def upgrade(raw: dict) -> dict:
    """Bring an older scenario file up to CURRENT_SCHEMA, one version at a time.

    When the format changes: bump CURRENT_SCHEMA and add a step here, e.g.
        if version == 1: raw = _v1_to_v2(raw); version = 2
    so old files keep loading instead of breaking.
    """
    version = raw.get("schema_version", 1)
    if version > CURRENT_SCHEMA:
        raise ScenarioError(f"schema_version {version} is newer than this app supports ({CURRENT_SCHEMA})")
    return {**raw, "schema_version": CURRENT_SCHEMA}


def parse_rules(raw: dict | None) -> GradingRules:
    if not raw:
        return GradingRules()
    cj = raw.get("crown_jewel", {})
    defaults = GradingRules()
    return GradingRules(
        crown_jewel_always=tuple(cj.get("always", defaults.crown_jewel_always)),
        crown_jewel_if_internet_facing=tuple(cj.get("if_internet_facing", defaults.crown_jewel_if_internet_facing)),
        p1_sla_days_ok=tuple(str(d) for d in raw.get("p1_sla_days_ok", defaults.p1_sla_days_ok)),
    )


class ScenarioError(ValueError):
    """Raised when a scenario file references something that doesn't exist."""


class ScenarioRepository:
    def __init__(self, directory: Path = DEFAULT_DIR):
        self.directory = Path(directory)
        self._scenarios: dict[str, Scenario] = {}
        for path in sorted(self.directory.glob("*.json")):
            scenario = self.load_file(path)
            self._scenarios[scenario.id] = scenario

    def all(self) -> list[Scenario]:
        return list(self._scenarios.values())

    def get(self, sid: str) -> Scenario | None:
        return self._scenarios.get(sid)

    @classmethod
    def load_file(cls, path: Path) -> Scenario:
        raw = upgrade(json.loads(Path(path).read_text()))
        scenario = Scenario(
            id=raw["id"],
            name=raw["name"],
            difficulty=raw["difficulty"],
            tagline=raw["tagline"],
            briefing=tuple(raw["briefing"]),
            constraints=Constraints(**raw.get("constraints", {})),
            zones=tuple(Zone(**z) for z in raw["zones"]),
            collector_zone=raw["collector_zone"],
            asset_groups=tuple(AssetGroup(**g) for g in raw["asset_groups"]),
            sources=tuple(Source(**{**s, "covers": tuple(s.get("covers", ()))}) for s in raw["sources"]),
            ticket_systems=tuple(TicketSystem(**t) for t in raw["ticket_systems"]),
            teams=tuple(Team(**t) for t in raw.get("teams", [])),
            rules=parse_rules(raw.get("rules")),
        )
        cls.validate(scenario, path.name)
        return scenario

    @staticmethod
    def validate(s: Scenario, name: str) -> None:
        zone_ids = {z.id for z in s.zones}
        group_ids = {g.id for g in s.asset_groups}
        ticket_ids = {t.id for t in s.ticket_systems}
        team_ids = {t.id for t in s.teams}
        problems = []
        if "saas" not in zone_ids:
            problems.append("every scenario needs a 'saas' zone (the platform may be drawn there)")
        if s.collector_zone not in zone_ids:
            problems.append(f"collector_zone {s.collector_zone!r} is not a zone")
        for item in (*s.asset_groups, *s.sources, *s.ticket_systems):
            if item.zone not in zone_ids:
                problems.append(f"{item.id}: unknown zone {item.zone!r}")
        for src in s.sources:
            for gid in src.covers:
                if gid not in group_ids:
                    problems.append(f"{src.id}: covers unknown asset group {gid!r}")
            if src.api_location not in ("saas", "onprem"):
                problems.append(f"{src.id}: api_location must be saas or onprem")
        for g in s.asset_groups:
            if g.owner is not None and g.owner not in team_ids:
                problems.append(f"{g.id}: owner {g.owner!r} is not a team")
        for t in s.teams:
            if t.kind not in ("dev", "ops"):
                problems.append(f"team {t.id}: kind must be dev or ops")
            if t.works_in not in ticket_ids:
                problems.append(f"team {t.id}: works_in {t.works_in!r} is not a ticket system")
        if problems:
            raise ScenarioError(f"{name}: " + "; ".join(problems))
