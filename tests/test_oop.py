"""OOP stage grading and the code it generates."""
import ast

from conftest import form

from exposure_sim.codegen import class_name, render_design
from exposure_sim.stages.oop import OopStage


def perfect_fields(s):
    fields = {"role_parse": "abstract", "role_fetch": "shared", "role_norm_hostname": "shared",
              "role_map_severity": "shared", "returns": "findings"}
    mid = len(s.paginated_sources) >= 2
    if mid:
        fields["paginated_class"] = "yes"
    for src in s.vuln_sources:
        ovr = ["parse"]
        if src.severity != "cvss":
            ovr.append("map_severity")
        paginated = src.transport == "api_paginated"
        fields[f"parent_{src.id}"] = "paginated" if (paginated and mid) else "base"
        if paginated and not mid:
            ovr.append("fetch")
        fields[f"ovr_{src.id}"] = ovr
    return fields


def run(scenario, fields):
    stage = OopStage()
    answer = stage.parse_form(form(**fields), scenario)
    return answer, stage.evaluate(scenario, answer)


def classes(code):
    tree = ast.parse(code)
    return {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}


def test_perfect_design(scenario):
    answer, ev = run(scenario, perfect_fields(scenario))
    assert ev.score == ev.max_score, [n.text for n in ev.notes if n.kind == "miss"]
    assert ev.pushback == []
    code = render_design(scenario, answer)
    assert "REVIEW" not in code


def test_generated_code_is_valid_python_and_structured(scenario):
    answer, _ = run(scenario, perfect_fields(scenario))
    cls = classes(render_design(scenario, answer))
    assert "BaseParser" in cls and "PaginatedApiParser" in cls
    for src in scenario.vuln_sources:
        node = cls[class_name(src)]
        parent = node.bases[0].id
        assert parent == ("PaginatedApiParser" if src.transport == "api_paginated" else "BaseParser")
        methods = {f.name for f in node.body if isinstance(f, ast.FunctionDef)}
        assert "parse" in methods
        assert ("map_severity" in methods) == (src.severity != "cvss")


def test_generated_base_marks_parse_abstract(scenario):
    answer, _ = run(scenario, perfect_fields(scenario))
    base = classes(render_design(scenario, answer))["BaseParser"]
    parse = next(f for f in base.body if isinstance(f, ast.FunctionDef) and f.name == "parse")
    assert any(getattr(d, "id", None) == "abstractmethod" for d in parse.decorator_list)


def test_generated_skeleton_actually_runs(repo):
    """Exec the generated code: the perfect design instantiates, a missing parse() raises TypeError."""
    s = repo.get("prairie-freight")
    answer, _ = run(s, perfect_fields(s))
    code = render_design(s, answer).replace("from models import Finding", "Finding = object")
    ns = {}
    exec(compile(code, "generated", "exec"), ns)
    ns["WizParser"]()

    bad = perfect_fields(s)
    bad["ovr_wiz"] = ["map_severity"]
    answer, ev = run(s, bad)
    ns = {}
    exec(compile(render_design(s, answer).replace("from models import Finding", "Finding = object"), "g", "exec"), ns)
    try:
        ns["WizParser"]()
        raise AssertionError("expected TypeError for a missing abstract method")
    except TypeError:
        pass
    assert any("WizParser doesn't override parse()" in q for q in ev.pushback)


def test_parse_shared_is_challenged(scenario):
    _, ev = run(scenario, {**perfect_fields(scenario), "role_parse": "shared"})
    assert any("forgets" in q for q in ev.pushback)


def test_no_middle_class_is_challenged(scenario):
    fields = perfect_fields(scenario)
    fields.pop("paginated_class", None)
    _, ev = run(scenario, fields)
    assert any("next page until done" in q for q in ev.pushback)


def test_severity_override_rules(repo):
    s = repo.get("prairie-freight")
    fields = perfect_fields(s)
    fields["ovr_tenable"] = ["parse"]                 # native 0-4 scale, needs mapping
    fields["ovr_snyk"] = ["parse", "map_severity"]   # already CVSS, doesn't
    answer, ev = run(s, fields)
    assert any("Tenable SC reports Native 0–4 severity" in q for q in ev.pushback)
    assert any("Snyk already ships a CVSS score" in q for q in ev.pushback)
    assert "REVIEW: Tenable SC reports" in render_design(s, answer)


def test_file_source_under_paginated_parent(repo):
    s = repo.get("prairie-freight")
    _, ev = run(s, {**perfect_fields(s), "parent_qualys": "paginated"})
    assert any("Qualys delivers CSV report export" in q for q in ev.pushback)


def test_hostname_override_breaks_correlation(scenario):
    src = scenario.vuln_sources[0]
    fields = perfect_fields(scenario)
    fields[f"ovr_{src.id}"] = fields[f"ovr_{src.id}"] + ["norm_hostname"]
    _, ev = run(scenario, fields)
    assert any("correlation" in q for q in ev.pushback)


def test_paginated_parent_ignored_without_middle_class(repo):
    """Picking the middle class as parent when it doesn't exist must not crash or award points."""
    s = repo.get("harbor-lane")
    fields = perfect_fields(s)
    fields.pop("paginated_class")
    answer, ev = run(s, fields)
    code = render_design(s, answer)
    ast.parse(code)
    assert "class PaginatedApiParser" not in code
    assert "(PaginatedApiParser)" not in code
