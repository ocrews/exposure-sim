"""Stage 2: decide where the platform runs and which way connections go."""
from exposure_sim.stages.base import Evaluation, Stage, register

MODELS = {
    "saas_direct": "SaaS only, API-to-API",
    "saas_collector": "SaaS + on-prem collector",
    "onprem": "Fully on-prem",
}
DIRECTIONS = {"outbound": "Collector dials out on 443", "inbound": "Platform connects in to the collector"}


@register
class DeploymentStage(Stage):
    id = "deployment"
    order = 2
    title = "Deployment model"
    goal = "Pick where the platform runs. If you use a collector, pick what it must reach and which way it connects."
    template = "stages/deployment.html"

    def context(self, scenario, answer):
        candidates = [*scenario.sources, *scenario.ticket_systems]
        # Offer everything not drawn in the SaaS zone, so look-alikes (the Qualys appliance) are a real choice
        local = [c for c in candidates if c.zone != "saas"]
        return {"models": MODELS, "directions": DIRECTIONS, "local_systems": local}

    def parse_form(self, form, scenario):
        ids = [s.id for s in scenario.sources] + [t.id for t in scenario.ticket_systems]
        return {
            "model": self.choice(form, "model", MODELS),
            "targets": self.checked(form, "targets", ids),
            "direction": self.choice(form, "direction", DIRECTIONS),
        }

    def evaluate(self, scenario, answer):
        ev = Evaluation()
        model, expected = answer.get("model"), scenario.expected_deployment
        onprem = scenario.onprem_endpoints
        onprem_labels = self.names(self._label(scenario, i) for i in sorted(onprem))

        ev.award(4 if model == expected else 0, 4,
                 good=f"{MODELS[expected]} fits this org.",
                 miss=f"Expected {MODELS[expected]}.")
        if model != expected:
            if model == "saas_direct" and onprem:
                ev.ask(f"{onprem_labels} only answer on the internal network. How does a SaaS platform "
                       "reach them without opening an inbound firewall rule?")
            elif model in ("saas_direct", "saas_collector") and scenario.constraints.data_must_stay_onprem:
                ev.ask(f"Read the constraint again: \"{scenario.constraints.reason}\" "
                       "Where would the findings be stored with this model?")
            elif model == "onprem":
                ev.ask("Nothing here forces data to stay inside. Who patches, backs up, and scales the "
                       "platform if the customer runs it themselves? Is that worth it for this org?")
            elif model == "saas_collector" and not onprem:
                ev.ask("Every system here already has a cloud API. What would the collector connect to?")
            else:
                ev.ask("Which of the customer's systems can only be reached from inside their network?")

        if expected == "saas_collector":
            targets = set(answer.get("targets", []))
            right, wrong = targets & onprem, targets - onprem
            ev.award(2 * len(right) - len(wrong), 2 * len(onprem),
                     good=f"The collector reaches exactly what the cloud can't: {onprem_labels}.",
                     miss=f"The collector only needs to reach {onprem_labels}.")
            for tid in sorted(wrong):
                obj = self._obj(scenario, tid)
                if obj.api_location == "saas":
                    ev.ask(f"{obj.label} sits on-prem, but where does its API live? "
                           f"{getattr(obj, 'note', '') or 'Check where its data ends up.'}")
            if onprem - targets:
                ev.ask(f"Which internal system would never be reached? Look at "
                       f"{self.names(self._label(scenario, i) for i in sorted(onprem - targets))}.")
            ev.award(2 if answer.get("direction") == "outbound" else 0, 2,
                     good="Outbound-only: one 443 rule out, nothing in. Security teams approve this fast.",
                     miss="The collector should dial out. Inbound connections from the internet need a firewall exception.")
            if answer.get("direction") == "inbound":
                ev.ask("If the platform connects in, what has to change on the customer's firewall? "
                       "How would their security team feel about that?")
            if any(t.api_location == "onprem" for t in scenario.ticket_systems):
                ev.tip("Ticket sync to an internal Jira still works: the collector polls for queued ticket work "
                       "and reports status back on its next call, like a ServiceNow MID Server.")
        elif expected == "onprem":
            ev.tip("Fully on-prem means the customer owns the database, HA, backups, and upgrades. "
                   "Ask the vendor what an air-gapped install and update path look like.")
        else:
            ev.tip("API-to-API: nothing to install. The work is creating read-only, scoped API keys in each tool.")
        return ev

    @staticmethod
    def _obj(scenario, oid):
        for item in (*scenario.sources, *scenario.ticket_systems):
            if item.id == oid:
                return item
        raise KeyError(oid)

    def _label(self, scenario, oid):
        return self._obj(scenario, oid).label
