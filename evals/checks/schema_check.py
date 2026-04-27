from pydantic import ValidationError

from brief_breakdown.schema import ProjectPlan


def check_schema(raw: dict) -> tuple[bool, str]:
    """Return (passed, message). raw is the model's JSON output as a dict."""
    try:
        ProjectPlan.model_validate(raw)
        return True, "ok"
    except ValidationError as e:
        return False, f"validation error: {e.errors()[:2]}"
