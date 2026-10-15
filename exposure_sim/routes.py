"""HTTP layer. Thin on purpose: load state, ask a Stage to parse and grade, save, render."""
from __future__ import annotations

from flask import (Blueprint, abort, current_app, jsonify, redirect, render_template, request,
                   url_for)

from exposure_sim.stages import STAGES, get_stage
from exposure_sim.topology import Overlay, TopologyBuilder

bp = Blueprint("game", __name__)


def repo():
    return current_app.extensions["scenarios"]


def store():
    return current_app.extensions["progress"]


def scenario_or_404(sid):
    scenario = repo().get(sid)
    if scenario is None:
        abort(404)
    return scenario


def first_open_stage(progress):
    return next((s for s in STAGES if not progress.is_locked(s.id)), None)


def summary(scenario, progress):
    """Score across locked stages, for the index and debrief."""
    rows, total, maximum = [], 0, 0
    for stage in STAGES:
        if not progress.is_locked(stage.id):
            continue
        ev = stage.evaluate(scenario, progress.answers.get(stage.id, {}))
        rows.append((stage, ev))
        total += ev.score
        maximum += ev.max_score
    return rows, total, maximum


@bp.get("/")
def index():
    cards = []
    for s in repo().all():
        progress = store().load(s.id)
        _, total, maximum = summary(s, progress)
        cards.append({"s": s, "done": len(progress.locked), "pct": round(100 * total / maximum) if maximum else None})
    return render_template("index.html", cards=cards, stage_count=len(STAGES))


@bp.get("/play/<sid>")
def play(sid):
    scenario = scenario_or_404(sid)
    nxt = first_open_stage(store().load(sid))
    if nxt is None:
        return redirect(url_for("game.debrief", sid=sid))
    return redirect(url_for("game.stage", sid=sid, stage_id=nxt.id))


@bp.route("/play/<sid>/<stage_id>", methods=["GET", "POST"])
def stage(sid, stage_id):
    scenario = scenario_or_404(sid)
    stage = get_stage(stage_id)
    if stage is None:
        abort(404)
    progress = store().load(sid)

    # Stages build on each other: you can't open stage N until N-1 is locked
    idx = STAGES.index(stage)
    if idx > 0 and not progress.is_locked(STAGES[idx - 1].id):
        return redirect(url_for("game.play", sid=sid))

    evaluation = None
    if request.method == "POST" and not progress.is_locked(stage.id):
        answer = stage.parse_form(request.form, scenario)
        progress.answers[stage.id] = answer
        evaluation = stage.evaluate(scenario, answer)
        if request.form.get("action") == "lock" or evaluation.strong:
            progress.lock(stage.id)
            store().save(sid, progress)
            return redirect(url_for("game.stage", sid=sid, stage_id=stage.id))   # post/redirect/get
        store().save(sid, progress)   # keep the draft so a refresh doesn't lose it

    locked = progress.is_locked(stage.id)
    answer = progress.answers.get(stage.id, {})
    if locked:
        evaluation = stage.evaluate(scenario, answer)
    nxt = STAGES[idx + 1] if idx + 1 < len(STAGES) else None
    layout = TopologyBuilder(scenario, Overlay.from_answers(progress.answers, set(progress.locked))).build()
    return render_template(
        "play.html", scenario=scenario, stage=stage, stages=STAGES, progress=progress,
        answer=answer, locked=locked, evaluation=evaluation, next_stage=nxt, layout=layout,
        **stage.context(scenario, answer),
    )


@bp.post("/play/<sid>/<stage_id>/retry")
def retry(sid, stage_id):
    scenario_or_404(sid)
    stage = get_stage(stage_id)
    if stage is None:
        abort(404)
    progress = store().load(sid)
    progress.unlock_from([s.id for s in STAGES[STAGES.index(stage):]])
    store().save(sid, progress)
    return redirect(url_for("game.stage", sid=sid, stage_id=stage_id))


@bp.get("/play/<sid>/debrief")
def debrief(sid):
    scenario = scenario_or_404(sid)
    progress = store().load(sid)
    rows, total, maximum = summary(scenario, progress)
    oop = get_stage("oop")
    code = None
    if progress.is_locked("oop"):
        code = oop.context(scenario, progress.answers.get("oop", {}))["code"]
    layout = TopologyBuilder(scenario, Overlay.from_answers(progress.answers, set(progress.locked))).build()
    return render_template("debrief.html", scenario=scenario, rows=rows, total=total, maximum=maximum,
                           code=code, layout=layout, stages=STAGES, progress=progress,
                           complete=len(rows) == len(STAGES))


@bp.post("/play/<sid>/reset")
def reset(sid):
    scenario_or_404(sid)
    store().reset(sid)
    return redirect(url_for("game.index"))


@bp.get("/play/<sid>/topology.json")
def topology_json(sid):
    """The same layout the page draws, as JSON, for other frontends or exports."""
    scenario = scenario_or_404(sid)
    progress = store().load(sid)
    return jsonify(TopologyBuilder(scenario, Overlay.from_answers(progress.answers, set(progress.locked))).build().to_dict())
