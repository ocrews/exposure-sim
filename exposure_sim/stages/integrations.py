"""Stage 1: read the map. Pick what to connect and spot what nothing scans."""
from exposure_sim.stages.base import Evaluation, Stage, register


@register
class IntegrationsStage(Stage):
    id = "integrations"
    order = 1
    title = "Integrations & gaps"
    goal = "Choose which sources the platform ingests, then mark the asset groups no vulnerability scanner covers."
    template = "stages/integrations.html"

    def parse_form(self, form, scenario):
        return {
            "connect": self.checked(form, "connect", [s.id for s in scenario.sources]),
            "gaps": self.checked(form, "gaps", [g.id for g in scenario.asset_groups]),
        }

    def evaluate(self, scenario, answer):
        ev = Evaluation()
        connected = set(answer.get("connect", []))
        marked = set(answer.get("gaps", []))

        missing = [s for s in scenario.vuln_sources if s.id not in connected]
        ev.award(2 * (len(scenario.vuln_sources) - len(missing)), 2 * len(scenario.vuln_sources),
                 good="Every vulnerability scanner is connected.",
                 miss=f"Not connected: {self.names(s.label for s in missing)}. Their findings never reach the platform.")
        for s in missing:
            covered = self.names(scenario.group(g).label for g in s.covers)
            ev.ask(f"You left {s.label} out. Where would findings for {covered} come from instead?")

        for src in scenario.context_sources:
            on = src.id in connected
            if src.kind == "cmdb":
                ev.award(2 if on else 0, 2,
                         good=f"{src.label} connected. Owners and criticality come from here.",
                         miss=f"{src.label} not connected, so findings have no owner and no business context.")
                if not on:
                    ev.ask("Without the CMDB, how does the platform decide which team gets a ticket, "
                           "or that one server matters more than another?")
            else:
                ev.award(1 if on else 0, 1,
                         good=f"{src.label} connected as an asset source. You can compare what exists against what's scanned.",
                         miss=f"{src.label} not connected. It's the best list of what actually exists, which is how you find unscanned machines.")

        gaps = scenario.coverage_gaps
        found, wrong = marked & gaps, marked - gaps
        ev.award(2 * len(found) - len(wrong), 2 * len(gaps),
                 good=f"Coverage gap spotted: {self.names(scenario.group(g).label for g in gaps)}.",
                 miss="Coverage gaps were missed or mislabeled.")
        if gaps - marked:
            ev.ask("Trace the scanner lines on the map. Is there an asset group with no scanner line touching it?")
        for gid in sorted(wrong):
            g = scenario.group(gid)
            who = [s.label for s in scenario.vuln_sources if gid in s.covers]
            ev.ask(f"You marked {g.label} as a gap, but {self.names(who)} scans it. What made it look uncovered?")
        for gid in sorted(found):
            g = scenario.group(gid)
            if g.platform == "ot":
                ev.tip(f"{g.label}: active scans can crash fragile OT gear. Passive network monitoring is the usual answer, not a Nessus scan.")
            else:
                ev.tip(f"{g.label}: report this to the customer as a coverage gap, with an owner and a date to fix it. Don't silently ignore it.")
        return ev
