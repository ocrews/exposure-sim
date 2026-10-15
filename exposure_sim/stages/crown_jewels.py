"""Stage 3: start small. Pick the wave-1 asset groups."""
from exposure_sim.stages.base import Evaluation, Stage, register


@register
class CrownJewelsStage(Stage):
    id = "crown_jewels"
    order = 3
    title = "Crown jewels"
    goal = "Pick the asset groups to onboard in wave 1. Start with what hurts most if breached."
    template = "stages/crown_jewels.html"

    def parse_form(self, form, scenario):
        return {"picks": self.checked(form, "picks", [g.id for g in scenario.asset_groups])}

    def evaluate(self, scenario, answer):
        ev = Evaluation()
        picks = set(answer.get("picks", []))
        expected = scenario.crown_jewels
        right, extra, missed = picks & expected, picks - expected, expected - picks

        ev.award(2 * len(right) - len(extra), 2 * len(expected),
                 good=f"Wave 1 is tight: {self.names(scenario.group(g).label for g in sorted(expected))}.",
                 miss="Wave 1 should be the critical systems plus high-value systems facing the internet.")

        for gid in sorted(missed):
            g = scenario.group(gid)
            why = "internet-facing" if g.internet_facing else f"rated {g.criticality}"
            ev.ask(f"{g.label} is {why}. If it were breached next week, would it matter that it wasn't in wave 1?")
        if len(picks) > len(expected) + 2:
            ev.ask(f"You picked {len(picks)} of {len(scenario.asset_groups)} groups. "
                   "If everything is wave 1, what does the first report look like to the CISO?")
        else:
            for gid in sorted(extra):
                g = scenario.group(gid)
                if g.criticality in ("low", "medium") and not g.internet_facing:
                    ev.ask(f"{g.label} is {g.criticality} and internal. Why onboard it before the systems "
                           "that would make the news?")
        for g in scenario.asset_groups:
            if g.id in expected and g.owner is None:
                ev.tip(f"{g.label} is a crown jewel with no owner in the CMDB. Fixing that ownership is "
                       "a wave-1 task in its own right.")
        r = scenario.rules
        rule = f"Rule used for this org: {self.names(r.crown_jewel_always)} systems"
        if r.crown_jewel_if_internet_facing:
            rule += f", plus {self.names(r.crown_jewel_if_internet_facing)} systems reachable from the internet"
        ev.tip(rule + ".")
        return ev
