"""Stage 6: design the integration layer as classes.

The player decides what the BaseParser contract looks like, whether a shared intermediate
class is worth it, and what each scanner's subclass inherits versus overrides. The rules
come from each source's traits in the scenario file (transport, severity format).
"""
from exposure_sim.codegen import class_name, render_design
from exposure_sim.stages.base import Evaluation, Stage, register

BASE_METHODS = {
    "parse": "Turn raw scanner data into Findings",
    "fetch": "Get the raw data (read a file or make a request)",
    "norm_hostname": "Clean a hostname: 'WEB01.corp.example' to 'web01'",
    "map_severity": "Convert a severity to the standard scale (default: from CVSS)",
}
ROLES = {
    "abstract": "Abstract: every subclass must write it",
    "shared": "Shared: written once here, inherited",
    "omit": "Not in the base class",
}
RETURNS = {
    "findings": "A list of Finding objects in the shared schema",
    "raw": "The vendor's raw JSON, untouched",
    "tickets": "Jira or ServiceNow tickets",
    "csv": "A CSV report",
}
OVERRIDABLE = ["parse", "fetch", "map_severity", "norm_hostname"]
TRANSPORT_TEXT = {
    "file": "Delivers an export file",
    "api": "One API request returns everything",
    "api_paginated": "API returns results one page at a time",
}


@register
class OopStage(Stage):
    id = "oop"
    order = 6
    title = "Integration classes"
    goal = "Design the parser classes: the BaseParser contract, an optional shared middle class, and what each scanner overrides."
    template = "stages/oop.html"

    def context(self, scenario, answer):
        return {
            "base_methods": BASE_METHODS, "roles": ROLES, "returns": RETURNS,
            "overridable": OVERRIDABLE, "transport_text": TRANSPORT_TEXT,
            "class_name": class_name,
            "code": render_design(scenario, answer) if answer else None,
        }

    def parse_form(self, form, scenario):
        scanners = {}
        for s in scenario.vuln_sources:
            scanners[s.id] = {
                "parent": self.choice(form, f"parent_{s.id}", ("base", "paginated"), "base"),
                "overrides": self.checked(form, f"ovr_{s.id}", OVERRIDABLE),
            }
        return {
            "roles": {m: self.choice(form, f"role_{m}", ROLES, "omit") for m in BASE_METHODS},
            "returns": self.choice(form, "returns", RETURNS),
            "paginated_class": form.get("paginated_class") == "yes",
            "scanners": scanners,
        }

    def evaluate(self, scenario, answer):
        ev = Evaluation()
        roles = answer.get("roles", {})
        mid = bool(answer.get("paginated_class"))
        scanners = answer.get("scanners", {})

        # ---- the contract ---------------------------------------------------------------
        parse_role = roles.get("parse")
        ev.award(3 if parse_role == "abstract" else 0, 3,
                 good="parse() is abstract: Python refuses to build a parser that doesn't implement it.",
                 miss="parse() should be abstract. It's the one method every scanner must write.")
        if parse_role == "shared":
            ev.ask("If BaseParser.parse() has a default body, what happens when someone adds a scanner and forgets "
                   "to write parse()? Would you rather find out at startup or in a customer's data?")
        elif parse_role == "omit":
            ev.ask("If parse() isn't on the base class, what method does the pipeline call on every parser?")

        for m in ("fetch", "norm_hostname", "map_severity"):
            role = roles.get(m)
            ev.award(1 if role == "shared" else 0, 1,
                     good=f"{m}() is shared: one implementation, inherited by every parser.",
                     miss=f"{m}() works best as a shared default that subclasses override only when needed.")
            if role == "abstract":
                ev.ask(f"With {m}() abstract, every scanner writes its own copy, even the ones that would do the "
                       "same thing. How many copies do you maintain when there's a bug?")
            elif role == "omit":
                ev.ask(f"If {m}() isn't on the base, where does that code live? Copied into each subclass?")

        ret = answer.get("returns")
        ev.award(2 if ret == "findings" else 0, 2,
                 good="parse() returns Findings in one shared schema, so nothing downstream knows which scanner it was.",
                 miss="parse() should return normalized Finding objects. That's the whole point of the contract.")
        if ret and ret != "findings":
            ev.ask(f"If parse() returns {RETURNS[ret].lower()}, what does the correlation step have to know "
                   "about every vendor's format?")

        # ---- the middle class -----------------------------------------------------------
        paginated = scenario.paginated_sources
        if len(paginated) >= 2:
            ev.award(2 if mid else 0, 2,
                     good=f"PaginatedApiParser holds the page-following loop once for {self.names(s.label for s in paginated)}.",
                     miss="Several scanners page through results. A shared middle class keeps that loop in one place.")
            if not mid:
                ev.ask(f"{self.names(s.label for s in paginated)} all return results one page at a time. "
                       "Where does the 'get next page until done' loop live in your design?")
        elif mid:
            ev.ask("Only one scanner here pages through results. Is a class with a single user worth it yet?")

        # ---- each scanner ---------------------------------------------------------------
        for s in scenario.vuln_sources:
            pick = scanners.get(s.id, {})
            ovr = set(pick.get("overrides", []))
            parent = pick.get("parent", "base") if mid else "base"
            name = class_name(s)
            pts = 0

            if "parse" in ovr:
                pts += 1
            else:
                ev.ask(f"{name} doesn't override parse(). Who teaches the pipeline to read {s.raw_format}?")

            wants_pages = s.transport == "api_paginated"
            if wants_pages:
                ok = (parent == "paginated" and "fetch" not in ovr) or (parent == "base" and "fetch" in ovr)
                if parent == "base" and "fetch" in ovr and mid:
                    ev.tip(f"{name} writes its own page loop even though PaginatedApiParser exists. Inherit it instead.")
                    ok = False
                if not ok and parent == "base" and "fetch" not in ovr:
                    ev.ask(f"{s.label} returns results one page at a time. Your {name} uses the default fetch(), "
                           "which makes one request. What happens to pages 2 through 40?")
                if parent == "paginated" and "fetch" in ovr:
                    ev.ask(f"{name} inherits from PaginatedApiParser and then overrides fetch(). "
                           "What did it inherit, then?")
            else:
                ok = parent == "base" and "fetch" not in ovr
                if parent == "paginated":
                    ev.ask(f"{s.label} delivers {s.raw_format}. Why would it inherit page-following?")
                elif "fetch" in ovr:
                    ev.ask(f"{s.label} delivers {s.raw_format}. What does your fetch() do that the shared default doesn't?")
            pts += ok

            needs_map = s.severity != "cvss"
            if needs_map == ("map_severity" in ovr):
                pts += 1
            elif needs_map:
                ev.ask(f"{s.label} reports {s.severity_note}. The shared map_severity() expects a CVSS number. "
                       "What does it do with that?")
            else:
                ev.ask(f"{s.label} already ships a CVSS score. What does your map_severity() override do "
                       "that the shared default doesn't?")

            if "norm_hostname" not in ovr:
                pts += 1
            else:
                ev.ask(f"Why would {s.label} need its own hostname rules? If each parser cleans hostnames "
                       "differently, will correlation still match the same server across tools?")

            ev.award(pts, 4, good=f"{name} overrides exactly what's different about {s.label}.",
                     miss=f"{name}: check what it inherits versus overrides.")
        ev.tip("Rule of thumb: put it in the base if every subclass does it the same way. Override only what differs.")
        return ev
