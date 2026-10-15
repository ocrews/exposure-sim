"""Stage 5: turn findings into work a team can actually do."""
from exposure_sim.stages.base import Evaluation, Stage, register

GROUP_KEYS = {
    "remediation": ("Remediation action", "e.g. 'Upgrade openssl to 3.0.15'"),
    "owner": ("Owning team", "Who does the work"),
    "platform": ("Platform / OS", "Windows fix vs Linux fix"),
    "cve": ("CVE ID", "One ticket per CVE"),
    "plugin": ("Scanner plugin / QID", "The scanner's own check ID"),
    "asset": ("Individual asset", "One ticket per host"),
}
FALLBACKS = {
    "triage": "Route to a VM triage queue with a named owner, and open a CMDB fix",
    "security": "Security team owns anything unowned",
    "skip": "Don't ticket unowned assets",
}
ROLLOUTS = {"pilot": "Pilot with one team, then expand", "all": "Turn on ticketing for every team on day one"}


@register
class TicketingStage(Stage):
    id = "ticketing"
    order = 5
    title = "Tickets & ownership"
    goal = "Choose how findings group into tickets, where each team's tickets go, and what happens to unowned assets."
    template = "stages/ticketing.html"

    def context(self, scenario, answer):
        return {"group_keys": GROUP_KEYS, "fallbacks": FALLBACKS, "rollouts": ROLLOUTS}

    def parse_form(self, form, scenario):
        systems = [t.id for t in scenario.ticket_systems]
        return {
            "keys": self.checked(form, "keys", GROUP_KEYS),
            "routes": {t.id: self.choice(form, f"route_{t.id}", systems) for t in scenario.teams},
            "fallback": self.choice(form, "fallback", FALLBACKS),
            "rollout": self.choice(form, "rollout", ROLLOUTS),
        }

    def evaluate(self, scenario, answer):
        ev = Evaluation()
        keys = set(answer.get("keys", []))
        for key, pts, good, miss in (
            ("remediation", 2, "Grouped by remediation action: one fix, one ticket.",
             "Without remediation in the key, one OpenSSL upgrade that fixes 5 CVEs becomes 5 tickets."),
            ("owner", 2, "Owner is in the key, so a ticket never spans two teams.",
             "Without owner, one ticket lands on several teams and nobody owns it."),
            ("platform", 2, "Platform is in the key: the Windows fix and the Linux fix are separate work.",
             "Without platform, 'block ICMP timestamp replies' puts a registry change and a sysctl change in one ticket."),
        ):
            ev.award(pts if key in keys else 0, pts, good=good, miss=miss)

        noisy = keys & {"cve", "plugin", "asset"}
        if noisy:
            ev.score = max(0, ev.score - len(noisy))
            ev.tip(f"Extra keys ({self.names(GROUP_KEYS[k][0] for k in sorted(noisy))}) split one fix into many tickets.")
        if "asset" in keys:
            ev.ask("One ticket per host: how many tickets does 'patch OpenSSL on 300 servers' create? "
                   "Will the team read ticket number 214?")
        if "cve" in keys and "remediation" not in keys:
            ev.ask("If one package upgrade fixes five CVEs, how many tickets does a CVE-based key create? "
                   "Does the team do five pieces of work?")
        if "plugin" in keys:
            ev.ask("Tenable and Qualys use different plugin IDs for the same flaw. What happens when both report it?")
        if "remediation" in keys and "platform" not in keys:
            ev.ask("'Disable ICMP timestamp responses' is a firewall rule on Windows and a sysctl/iptables change on "
                   "Linux. Should both be one ticket?")
        if "remediation" in keys and "owner" not in keys:
            ev.ask("If the same fix applies to servers owned by three teams, who closes the ticket?")

        routes = answer.get("routes", {})
        wrong = [t for t in scenario.teams if routes.get(t.id) != t.works_in]
        n = len(scenario.teams)
        ev.award(n - len(wrong), n, good="Every team gets tickets where it already works.",
                 miss=f"Misrouted: {self.names(t.id for t in wrong)}.")
        if wrong:
            t = wrong[0]
            ev.ask(f"{t.id} works in {scenario.ticket_system(t.works_in).label}. "
                   "If their tickets land somewhere else, who sees them?")

        fb = answer.get("fallback")
        ev.award({"triage": 2, "security": 1}.get(fb, 0), 2,
                 good="Unowned findings go to a named triage queue, and the CMDB gap gets fixed.",
                 miss="Best practice: a named triage queue plus a ticket to fix the CMDB record.")
        unowned = scenario.unowned_groups
        if fb == "skip" and unowned:
            ev.ask(f"{self.names(g.label for g in unowned)} has no owner. With this rule, when does anyone "
                   "find out about its vulnerabilities?")
        elif fb == "security":
            ev.ask("If security owns every unowned asset forever, does the CMDB ever get fixed?")

        ro = answer.get("rollout")
        ev.award(2 if ro == "pilot" else 0, 2, good="Pilot first: tune grouping and routing on one team before everyone sees it.",
                 miss="Turning ticketing on for everyone at once risks a ticket flood on day one.")
        if ro == "all":
            ev.ask(f"{n} teams wake up to new tickets on Monday, and some are grouped wrong. "
                   "What do they think of the platform by Tuesday?")
        return ev
