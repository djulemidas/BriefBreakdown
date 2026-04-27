from brief_breakdown.schema import ProjectPlan
from evals.checks.business_rules import (
    deps_resolve,
    each_phase_has_task,
    hours_consistent,
    no_dep_cycles,
)
from evals.checks.coverage_check import coverage


def make_plan(**overrides) -> ProjectPlan:
    base = {
        "project_summary": "x",
        "estimated_total_hours": 30,
        "phases": ["discovery", "build", "qa"],
        "tasks": [
            {"id": "t1", "title": "Kickoff workshop", "description": "discovery session", "role": "pm", "phase": "discovery", "estimate_hours": 5, "depends_on": []},
            {"id": "t2", "title": "Implement feature", "description": "build it", "role": "developer", "phase": "build", "estimate_hours": 20, "depends_on": ["t1"]},
            {"id": "t3", "title": "QA pass", "description": "test", "role": "qa", "phase": "qa", "estimate_hours": 5, "depends_on": ["t2"]},
        ],
        "milestones": [],
        "risks": [],
    }
    base.update(overrides)
    return ProjectPlan.model_validate(base)


def test_hours_consistent_passes():
    ok, _ = hours_consistent(make_plan())
    assert ok


def test_hours_drift_caught():
    plan = make_plan(estimated_total_hours=100)
    ok, msg = hours_consistent(plan)
    assert not ok
    assert "drift" in msg


def test_deps_resolve_passes():
    ok, _ = deps_resolve(make_plan())
    assert ok


def test_deps_unresolved_caught():
    plan = make_plan()
    plan.tasks[1].depends_on = ["t99"]
    ok, _ = deps_resolve(plan)
    assert not ok


def test_self_dependency_caught():
    plan = make_plan()
    plan.tasks[1].depends_on = ["t2"]
    ok, _ = deps_resolve(plan)
    assert not ok


def test_no_dep_cycles_passes():
    ok, _ = no_dep_cycles(make_plan())
    assert ok


def test_dep_cycle_caught():
    plan = make_plan()
    plan.tasks[0].depends_on = ["t3"]
    ok, msg = no_dep_cycles(plan)
    assert not ok
    assert "cycle" in msg


def test_each_phase_populated():
    ok, _ = each_phase_has_task(make_plan())
    assert ok


def test_empty_phase_caught():
    plan = make_plan(phases=["discovery", "build", "qa", "launch"])
    ok, msg = each_phase_has_task(plan)
    assert not ok
    assert "launch" in msg


def test_coverage_full_recall():
    plan = make_plan()
    recall, missing = coverage(plan, ["kickoff", "qa"])
    assert recall == 1.0
    assert missing == []


def test_coverage_partial():
    plan = make_plan()
    recall, missing = coverage(plan, ["kickoff", "training"])
    assert recall == 0.5
    assert missing == ["training"]
