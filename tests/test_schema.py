import pytest
from pydantic import ValidationError

from brief_breakdown.schema import ProjectPlan, Task
from evals.checks.schema_check import check_schema


def _valid_plan() -> dict:
    return {
        "project_summary": "Test",
        "estimated_total_hours": 20,
        "phases": ["discovery", "build", "qa"],
        "tasks": [
            {"id": "t1", "title": "Kickoff", "description": "x", "role": "pm", "phase": "discovery", "estimate_hours": 5, "depends_on": []},
            {"id": "t2", "title": "Build", "description": "x", "role": "developer", "phase": "build", "estimate_hours": 10, "depends_on": ["t1"]},
            {"id": "t3", "title": "QA", "description": "x", "role": "qa", "phase": "qa", "estimate_hours": 5, "depends_on": ["t2"]},
        ],
        "milestones": [{"name": "m", "phase": "build"}],
        "risks": [{"risk": "r", "severity": "low", "mitigation": "m"}],
    }


# -- direct model validation ---------------------------------------------


def test_valid_plan_parses():
    plan = ProjectPlan.model_validate(_valid_plan())
    assert len(plan.tasks) == 3


def test_invalid_role_rejected():
    bad = _valid_plan()
    bad["tasks"][0]["role"] = "ceo"
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(bad)


def test_invalid_phase_rejected():
    bad = _valid_plan()
    bad["tasks"][0]["phase"] = "marketing"
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(bad)


def test_negative_hours_rejected():
    bad = _valid_plan()
    bad["tasks"][0]["estimate_hours"] = 0
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(bad)


def test_hours_above_cap_rejected():
    bad = _valid_plan()
    bad["tasks"][0]["estimate_hours"] = 500  # cap is 400
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(bad)


def test_invalid_severity_rejected():
    bad = _valid_plan()
    bad["risks"][0]["severity"] = "catastrophic"
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(bad)


def test_missing_required_field_rejected():
    bad = _valid_plan()
    del bad["estimated_total_hours"]
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(bad)


def test_task_without_description_rejected():
    bad = _valid_plan()
    del bad["tasks"][0]["description"]
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(bad)


def test_task_depends_on_defaults_to_empty_list():
    raw = _valid_plan()
    del raw["tasks"][0]["depends_on"]
    plan = ProjectPlan.model_validate(raw)
    assert plan.tasks[0].depends_on == []


def test_invalid_phase_in_phases_array_rejected():
    bad = _valid_plan()
    bad["phases"] = ["discovery", "marketing"]
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(bad)


# -- schema_check wrapper -------------------------------------------------


def test_check_schema_passes_on_valid_plan():
    ok, msg = check_schema(_valid_plan())
    assert ok
    assert msg == "ok"


def test_check_schema_fails_on_bad_role():
    bad = _valid_plan()
    bad["tasks"][0]["role"] = "ceo"
    ok, msg = check_schema(bad)
    assert not ok
    assert "validation error" in msg


def test_check_schema_fails_on_missing_field():
    bad = _valid_plan()
    del bad["tasks"]
    ok, _ = check_schema(bad)
    assert not ok
