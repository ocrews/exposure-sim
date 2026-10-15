import sys
from pathlib import Path

import pytest
from werkzeug.datastructures import MultiDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from exposure_sim.scenarios import ScenarioRepository  # noqa: E402


@pytest.fixture(scope="session")
def repo():
    return ScenarioRepository()


@pytest.fixture(params=["harbor-lane", "prairie-freight", "regional-bureau"])
def scenario(request, repo):
    return repo.get(request.param)


def form(**fields) -> MultiDict:
    """Build a form the way a browser submits it: lists become repeated keys (checkbox groups)."""
    items = []
    for key, value in fields.items():
        for v in value if isinstance(value, (list, tuple, set)) else [value]:
            items.append((key, v))
    return MultiDict(items)
