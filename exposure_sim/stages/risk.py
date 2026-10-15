"""Stage 4: decide what 'risk' means. Severity is not risk."""
from exposure_sim.stages.base import Evaluation, Note, Stage, register

SIGNALS = {
    "cvss": ("CVSS base score", "How bad the flaw is in theory."),
    "kev": ("CISA KEV", "Is it being exploited right now?"),
    "epss": ("EPSS probability", "How likely is exploitation in the next 30 days?"),
    "exposure": ("Internet exposure", "Can an attacker reach it without a foothold?"),
    "criticality": ("Asset criticality", "What breaks if this asset is compromised?"),
    "scanner_count": ("Number of scanners reporting it", "How many tools flagged the same finding."),
}
KEV_POLICIES = {
    "targeted": "KEV on a crown jewel or internet-facing asset goes straight to P1",
    "everywhere": "Every KEV finding is P1, wherever it is",
    "none": "KEV gets no special treatment",
}
SLAS = ["3", "7", "15", "30"]


@register
class RiskStage(Stage):
    id = "risk"
    order = 4
    title = "Risk scoring"
    goal = "Choose the signals that make up a finding's risk, how KEV is handled, and the P1 deadline."
    template = "stages/risk.html"

    def context(self, scenario, answer):
        return {"signals": SIGNALS, "kev_policies": KEV_POLICIES, "slas": SLAS}

    def parse_form(self, form, scenario):
        return {
            "signals": self.checked(form, "signals", SIGNALS),
            "kev_policy": self.choice(form, "kev_policy", KEV_POLICIES),
            "p1_sla": self.choice(form, "p1_sla", SLAS),
        }

    def evaluate(self, scenario, answer):
        ev = Evaluation()
        sig = set(answer.get("signals", []))
        has = sig.__contains__

        ev.award(1 if has("cvss") else 0, 1, good="CVSS kept as the base severity.",
                 miss="Drop CVSS entirely and you lose how bad the flaw is in theory. Keep it as a base.")
        ev.award(2 if has("kev") else 0, 2, good="KEV included: known exploitation outranks theory.",
                 miss="No KEV. Actively exploited flaws look the same as theoretical ones.")
        ev.award(1 if has("epss") else 0, 1, good="EPSS included to rank everything that isn't KEV yet.",
                 miss="No EPSS. You lose a way to rank the large middle that isn't on KEV.")
        ev.award(2 if has("exposure") else 0, 2, good="Exposure included: reachable flaws rank higher.",
                 miss="No exposure signal. An internal test box and the public portal score the same.")
        ev.award(2 if has("criticality") else 0, 2, good="Asset criticality included: the business context.",
                 miss="No criticality. The billing database and a printer are equal.")
        if has("scanner_count"):
            ev.score = max(0, ev.score - 1)
            ev.notes.append(Note("miss", "Scanner count is a data-quality fact, not risk. Three tools agreeing doesn't make a flaw more dangerous."))
            ev.ask("If Tenable and Qualys both report the same CVE, is the box twice as likely to be breached?")

        if not (has("kev") and has("exposure")):
            ev.ask("Say there are 40,000 findings at CVSS 7 or higher. Without KEV and exposure, which "
                   "800 does a team start on Monday?")
        if sig == {"cvss"}:
            ev.ask("CVSS describes the flaw, not your environment. What does it know about where the asset sits?")

        policy = answer.get("kev_policy")
        ev.award({"targeted": 2, "everywhere": 1}.get(policy, 0), 2,
                 good="KEV forces P1 where it matters, not on every isolated printer.",
                 miss="Targeted KEV handling works best: P1 when it's on a crown jewel or facing the internet.")
        if policy == "everywhere":
            ev.ask("A KEV finding on an isolated lab printer and on the internet-facing portal: same 7-day deadline "
                   "for both? What does that do to the P1 queue?")
        elif policy == "none" or policy is None:
            ev.ask("Attackers are already using KEV flaws. Why would those wait in the normal queue?")

        sla = answer.get("p1_sla")
        ev.award(1 if sla in scenario.rules.p1_sla_days_ok else 0, 1, good=f"P1 deadline of {sla} days is realistic and defensible.",
                 miss="P1 deadlines usually land at 7 to 15 days. Too short gets ignored, too long isn't urgent.")
        if sla == "3":
            ev.ask("Can a change board approve and a team patch production in 3 days, every time? What happens to an SLA nobody can meet?")
        elif sla == "30":
            ev.ask("If a flaw is being exploited today, what does an attacker do with the next 30 days?")
        if scenario.constraints.data_must_stay_onprem:
            ev.tip("Federal customers often already have KEV due dates set by policy. Map those dates into the SLA "
                   "rules so the platform reports compliance in the terms they're audited on.")
        return ev
