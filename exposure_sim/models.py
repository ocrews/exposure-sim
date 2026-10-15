"""Domain model for a scenario: the existing organization the player walks into.

Everything the game grades against is DERIVED from this data (crown jewels, coverage gaps,
the right deployment model, which methods a parser must override). Adding a scenario means
writing a JSON file, not touching grading code.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Source kinds that produce vulnerability findings (vs. context-only sources)
VULN_KINDS = {"infra", "cloud", "container", "appsec", "endpoint"}
CONTEXT_KINDS = {"cmdb", "edr"}
CRITICALITY_ORDER = ["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class Zone:
    id: str
    label: str
    kind: str  # saas | cloud | servers | mgmt | dmz | office | ot | cluster


@dataclass(frozen=True)
class Team:
    id: str
    works_in: str      # id of the ticket system this team actually uses
    kind: str = "ops"  # dev | ops, shown to the player; the briefing says where each kind works


@dataclass(frozen=True)
class AssetGroup:
    id: str
    label: str
    zone: str
    count: int
    platform: str  # linux | windows | container | repo | mixed | iot | ot
    criticality: str
    internet_facing: bool
    owner: str | None  # None = not in the CMDB, nobody owns it on paper
    note: str = ""



@dataclass(frozen=True)
class Source:
    """A tool the platform could integrate: a scanner, the CMDB, or EDR inventory."""
    id: str
    label: str
    vendor_note: str
    kind: str
    zone: str                      # where it is drawn (where the box physically lives)
    api_location: str              # "saas" or "onprem": where its API must be reached from
    covers: tuple[str, ...] = ()   # asset group ids it scans
    transport: str = "api"         # file | api | api_paginated
    severity: str = "cvss"         # cvss | native (vendor 0-4 / 1-5 scale) | labels
    severity_note: str = ""
    raw_format: str = "JSON"
    note: str = ""

    @property
    def is_vuln_source(self) -> bool:
        return self.kind in VULN_KINDS


@dataclass(frozen=True)
class TicketSystem:
    id: str
    label: str
    zone: str
    api_location: str


@dataclass(frozen=True)
class GradingRules:
    """Per-scenario grading policy, read from the scenario file so a new org can grade differently
    without code changes. Defaults match common practice."""
    crown_jewel_always: tuple[str, ...] = ("critical",)
    crown_jewel_if_internet_facing: tuple[str, ...] = ("high",)
    p1_sla_days_ok: tuple[str, ...] = ("7", "15")

    def is_crown_jewel(self, g: "AssetGroup") -> bool:
        return (g.criticality in self.crown_jewel_always
                or (g.internet_facing and g.criticality in self.crown_jewel_if_internet_facing))


@dataclass(frozen=True)
class Constraints:
    data_must_stay_onprem: bool = False
    reason: str = ""


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    difficulty: str
    tagline: str
    briefing: tuple[str, ...]
    constraints: Constraints
    zones: tuple[Zone, ...]
    collector_zone: str
    asset_groups: tuple[AssetGroup, ...]
    sources: tuple[Source, ...]
    ticket_systems: tuple[TicketSystem, ...]
    teams: tuple[Team, ...] = field(default=())
    rules: GradingRules = field(default_factory=GradingRules)

    # ---- lookups ----------------------------------------------------------------------
    def zone(self, zid: str) -> Zone:
        return next(z for z in self.zones if z.id == zid)

    def source(self, sid: str) -> Source:
        return next(s for s in self.sources if s.id == sid)

    def group(self, gid: str) -> AssetGroup:
        return next(g for g in self.asset_groups if g.id == gid)

    def ticket_system(self, tid: str) -> TicketSystem:
        return next(t for t in self.ticket_systems if t.id == tid)

    # ---- derived truths the game grades against ---------------------------------------
    @property
    def vuln_sources(self) -> list[Source]:
        return [s for s in self.sources if s.is_vuln_source]

    @property
    def context_sources(self) -> list[Source]:
        return [s for s in self.sources if s.kind in CONTEXT_KINDS]

    @property
    def crown_jewels(self) -> set[str]:
        return {g.id for g in self.asset_groups if self.rules.is_crown_jewel(g)}

    @property
    def coverage_gaps(self) -> set[str]:
        """Asset groups no vulnerability scanner covers."""
        covered = {gid for s in self.vuln_sources for gid in s.covers}
        return {g.id for g in self.asset_groups if g.id not in covered}

    @property
    def unowned_groups(self) -> list[AssetGroup]:
        return [g for g in self.asset_groups if g.owner is None]

    @property
    def onprem_endpoints(self) -> set[str]:
        """Systems whose API is only reachable from inside the network."""
        ids = {s.id for s in self.sources if s.api_location == "onprem"}
        return ids | {t.id for t in self.ticket_systems if t.api_location == "onprem"}

    @property
    def expected_deployment(self) -> str:
        if self.constraints.data_must_stay_onprem:
            return "onprem"
        if self.onprem_endpoints:
            return "saas_collector"
        return "saas_direct"

    @property
    def paginated_sources(self) -> list[Source]:
        return [s for s in self.vuln_sources if s.transport == "api_paginated"]
