"""Turn the player's class design into readable Python.

The generated code is a skeleton (method bodies are `...`), but the class structure,
inheritance, abstract methods, and overrides are exactly what the player chose. Weak choices
get a `# REVIEW:` comment so the code itself shows what to fix. The output is checked with
`ast.parse` in the tests, so it is always valid Python.
"""
from __future__ import annotations

from exposure_sim.models import Scenario, Source

RETURN_TYPES = {"findings": "list[Finding]", "raw": "dict", "tickets": "list[Ticket]", "csv": "str"}

BASE_BODIES = {
    "parse": ("parse(self, raw) -> {ret}", "Turn this source's raw data into normalized findings."),
    "fetch": ("fetch(self, source)", "Default: read one export file or make one request."),
    "norm_hostname": ("norm_hostname(self, raw: str) -> str", "'WEB01.corp.example' -> 'web01', the same way for every source."),
    "map_severity": ("map_severity(self, raw) -> str", "Default: CVSS number -> critical/high/medium/low."),
}


def class_name(source: Source) -> str:
    return "".join(part.capitalize() for part in source.id.replace("_", "-").split("-")) + "Parser"


def _method(sig: str, doc: str, indent: str = "    ", abstract: bool = False, review: str | None = None) -> list[str]:
    lines = []
    if review:
        lines.append(f"{indent}# REVIEW: {review}")
    if abstract:
        lines.append(f"{indent}@abstractmethod")
    lines.append(f"{indent}def {sig}:")
    lines.append(f'{indent}    """{doc}"""')
    if not abstract:
        lines.append(f"{indent}    ...")
    return lines


def render_design(scenario: Scenario, answer: dict) -> str:
    roles = answer.get("roles", {})
    ret = RETURN_TYPES.get(answer.get("returns"), "list[Finding]")
    mid = bool(answer.get("paginated_class"))
    scanners = answer.get("scanners", {})

    out = [
        f'"""Integration layer for {scenario.name} (generated from your design)."""',
        "from abc import ABC, abstractmethod",
        "",
        "from models import Finding",
        "",
        "",
        "class BaseParser(ABC):",
        '    """Contract: every source becomes the same Finding objects."""',
    ]
    if answer.get("returns") not in (None, "findings"):
        out.append(f"    # REVIEW: parse() returns {ret}. Downstream code now has to understand every vendor.")
    any_method = False
    for m, (sig, doc) in BASE_BODIES.items():
        role = roles.get(m, "omit")
        if role == "omit":
            out.append("")
            out.append(f"    # {m}() is not defined here, so each subclass needs its own copy.")
            continue
        review = None
        if m == "parse" and role == "shared":
            review = "a default parse() means a parser that forgets to implement it still builds."
        elif m != "parse" and role == "abstract":
            review = f"every subclass must now write {m}(), even when they'd all do the same thing."
        out.append("")
        out += _method(sig.format(ret=ret), doc, abstract=(role == "abstract"), review=review)
        any_method = True
    if not any_method:
        out.append("    pass")

    paginated = scenario.paginated_sources
    if mid:
        out += ["", "", "class PaginatedApiParser(BaseParser):",
                '    """Shared by every API that returns results one page at a time."""']
        if len(paginated) < 2:
            out.append("    # REVIEW: only one scanner here paginates. A class with one user may be premature.")
        out += ["", "    def fetch(self, source):",
                '        """Follow the next-page link or cursor until there are no more pages."""',
                "        page = source.first_page()",
                "        while page:",
                "            yield from page.items",
                "            page = source.next_page(page)"]

    for s in scenario.vuln_sources:
        pick = scanners.get(s.id, {})
        parent = "PaginatedApiParser" if (mid and pick.get("parent") == "paginated") else "BaseParser"
        ovr = set(pick.get("overrides", []))
        out += ["", "", f"class {class_name(s)}({parent}):",
                f'    """{s.label}: {s.raw_format}. Severity: {s.severity_note or "CVSS"}."""']
        body = []
        if "parse" in ovr:
            body += [""] + _method(f"parse(self, raw) -> {ret}", f"Map {s.label} fields onto Finding.")
        elif roles.get("parse") == "abstract":
            body += ["", f"    # REVIEW: parse() is abstract and not implemented, so {class_name(s)}() raises TypeError."]

        if "fetch" in ovr:
            review = None
            if parent == "PaginatedApiParser":
                review = "this replaces the page loop it just inherited."
            elif s.transport == "api_paginated" and mid:
                review = "PaginatedApiParser already has this loop. Inherit it instead."
            elif s.transport != "api_paginated":
                review = f"{s.label} delivers {s.raw_format}; the shared fetch() already handles that."
            doc = "Follow pages until done." if s.transport == "api_paginated" else "Custom fetch."
            body += [""] + _method("fetch(self, source)", doc, review=review)
        elif s.transport == "api_paginated" and parent == "BaseParser":
            body += ["", "    # REVIEW: this API pages results, but the inherited fetch() makes one request."]
        if parent == "PaginatedApiParser" and s.transport != "api_paginated":
            body += ["", f"    # REVIEW: {s.label} doesn't page results. Why inherit page-following?"]

        needs_map = s.severity != "cvss"
        if "map_severity" in ovr:
            review = None if needs_map else f"{s.label} already ships CVSS; the shared default handles it."
            body += [""] + _method("map_severity(self, raw) -> str", f"{s.severity_note} -> standard scale.", review=review)
        elif needs_map:
            body += ["", f"    # REVIEW: {s.label} reports {s.severity_note}; the inherited CVSS mapping won't understand it."]

        if "norm_hostname" in ovr:
            body += [""] + _method("norm_hostname(self, raw: str) -> str", "Custom hostname rules.",
                                   review="different hostname rules per scanner break correlation across tools.")
        out += body if any(line.strip() for line in body) else ["    pass  # inherits everything"]
    return "\n".join(out) + "\n"
