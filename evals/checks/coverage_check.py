"""Coverage check: did the generated plan mention the things this brief implies?

For each example in the golden dataset we hand-label a small set of
`required_signals` — short tokens that any sensible plan for that brief should
contain ("magento", "klaviyo", "training", etc.). The check measures recall:
how many of the required signals appear somewhere in the plan's free-text
fields.

This is the cheapest possible proxy for "the model paid attention to the
brief". A keyword-recall score of 1.0 doesn't mean the plan is good, but a
score of 0.3 reliably means the plan has missed something important. Pair it
with the LLM-as-judge dimension for the qualitative side.
"""

from brief_breakdown.schema import ProjectPlan


def _haystack(plan: ProjectPlan) -> str:
    """Concatenate every free-text field on the plan into one lowercased blob.

    We include the project summary, every task title and description, and every
    risk statement. Roles, phases, and ids are excluded because they are closed
    enums chosen by the schema, not by the model's understanding of the brief.
    """
    parts = [plan.project_summary]
    for t in plan.tasks:
        parts.append(t.title)
        parts.append(t.description)
    for r in plan.risks:
        parts.append(r.risk)
    return " ".join(parts).lower()


def coverage(plan: ProjectPlan, required_signals: list[str]) -> tuple[float, list[str]]:
    """Return (recall, missing_signals) for the given plan.

    What it tests: surface-level evidence that the model engaged with the
    specifics of the brief (technologies, integrations, constraints).
    How: case-insensitive substring match of each signal against the
    concatenated free-text fields. Returns the fraction found and the list of
    missing signals so the report can show *which* keywords were missed.
    Why: catches the most common failure mode of any structured-generation
    feature — generic boilerplate that ignores brief-specific details.
    Limitations:
      - Substring matching means "training" hits "trainee" by accident.
      - A semantically equivalent phrasing that misses the literal token is
        scored as a miss. The thresholds in the runner are set with this in
        mind: aim for >0.7 mean recall, not 1.0.
      - Multi-word signals must appear contiguously (e.g., "case study" only
        matches the bigram, not "studies of cases").
    """
    if not required_signals:
        return 1.0, []
    text = _haystack(plan)
    missing = [s for s in required_signals if s.lower() not in text]
    found = len(required_signals) - len(missing)
    return found / len(required_signals), missing
