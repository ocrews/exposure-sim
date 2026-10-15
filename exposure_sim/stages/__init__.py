"""Importing this package registers every stage, in order, in STAGES."""
from exposure_sim.stages import crown_jewels, deployment, integrations, oop, risk, ticketing  # noqa: F401
from exposure_sim.stages.base import STAGES, Evaluation, Stage, get_stage  # noqa: F401
