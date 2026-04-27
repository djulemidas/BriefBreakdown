from brief_breakdown.schema import ProjectPlan


def _haystack(plan: ProjectPlan) -> str:
    parts = [plan.project_summary]
    for t in plan.tasks:
        parts.append(t.title)
        parts.append(t.description)
    for r in plan.risks:
        parts.append(r.risk)
    return " ".join(parts).lower()


def coverage(plan: ProjectPlan, required_signals: list[str]) -> tuple[float, list[str]]:
    """Return (recall, missing_signals).

    Each signal is matched as a case-insensitive substring against task titles,
    descriptions, the project summary, and risk text. This is a deliberately
    cheap check that catches obvious omissions like "no QA task at all".
    """
    if not required_signals:
        return 1.0, []
    text = _haystack(plan)
    missing = [s for s in required_signals if s.lower() not in text]
    found = len(required_signals) - len(missing)
    return found / len(required_signals), missing
