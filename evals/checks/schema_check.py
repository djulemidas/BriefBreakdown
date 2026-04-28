"""Schema check: does the generated output parse as a `ProjectPlan`?

With OpenAI structured outputs this is essentially a tripwire — the SDK is
responsible for forcing the model into our schema, so failures here usually
indicate an SDK or schema change rather than a bad generation. We keep the
check anyway because if it ever fires, downstream eval dimensions will all
crash on missing fields, and we want a single clear failure message at the top
of the report.
"""

from pydantic import ValidationError

from brief_breakdown.schema import ProjectPlan


def check_schema(raw: dict) -> tuple[bool, str]:
    """Return (passed, message). `raw` is the model's JSON output as a dict.

    What it tests: structural conformance to the `ProjectPlan` Pydantic model.
    How: `ProjectPlan.model_validate(raw)` — fails on missing required fields,
    invalid `Literal` values for role/phase/severity, negative hours, etc.
    Why: serves as a fast-fail gate before the more expensive coverage,
    business-rule, and judge dimensions try to read fields that may not exist.
    """
    try:
        ProjectPlan.model_validate(raw)
        return True, "ok"
    except ValidationError as e:
        return False, f"validation error: {e.errors()[:2]}"
