import pytest
from pydantic import ValidationError

from brief_breakdown.schema import ProjectPlan, Task


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


def test_invalid_severity_rejected():
    bad = _valid_plan()
    bad["risks"][0]["severity"] = "catastrophic"
    with pytest.raises(ValidationError):
        ProjectPlan.model_validate(bad)
