"""Tests for the pure aggregation and rendering functions in the runner.

We don't test `evaluate_one` here because it calls the live OpenAI API.
The functions covered below operate on the dict shape that `evaluate_one`
produces, so they're easy to test in isolation with handwritten fixtures.
"""

from evals.runners.run_evals import aggregate, render_markdown


def _result(
    *,
    id: str,
    schema_ok: bool = True,
    recall: float = 1.0,
    rules_passed: int = 7,
    rules_total: int = 7,
    judge_scores: dict | None = None,
    task_count: int = 5,
    total_hours: int = 100,
) -> dict:
    return {
        "id": id,
        "schema": {"ok": schema_ok, "msg": "ok" if schema_ok else "err"},
        "coverage": {"recall": recall, "missing": []},
        "business_rules": {
            "passed": rules_passed,
            "total": rules_total,
            "details": [],
        },
        "judge": {"scores": judge_scores} if judge_scores else None,
        "task_count": task_count,
        "total_hours": total_hours,
    }


def test_aggregate_perfect_run():
    results = [
        _result(id="a", judge_scores={"realism": 5, "completeness": 5, "specificity": 5}),
        _result(id="b", judge_scores={"realism": 5, "completeness": 5, "specificity": 5}),
    ]
    agg = aggregate(results)
    assert agg["n"] == 2
    assert agg["schema_pass_rate"] == 1.0
    assert agg["coverage_mean_recall"] == 1.0
    assert agg["business_rules_pass_rate"] == 1.0
    assert agg["judge_avg"]["realism"] == 5
    assert agg["judge_avg"]["completeness"] == 5
    assert agg["judge_avg"]["specificity"] == 5


def test_aggregate_mixed_run():
    results = [
        _result(id="a", schema_ok=True, recall=1.0, rules_passed=7, rules_total=7),
        _result(id="b", schema_ok=False, recall=0.5, rules_passed=5, rules_total=7),
    ]
    agg = aggregate(results)
    assert agg["n"] == 2
    assert agg["schema_pass_rate"] == 0.5
    assert agg["coverage_mean_recall"] == 0.75
    # rules pass rate = mean of (7/7, 5/7)
    assert abs(agg["business_rules_pass_rate"] - (1.0 + 5 / 7) / 2) < 1e-9


def test_aggregate_skips_judge_when_absent():
    results = [_result(id="a"), _result(id="b")]  # no judge scores
    agg = aggregate(results)
    assert agg["judge_avg"] == {}


def test_aggregate_handles_judge_errors():
    # A failed judge call records {"error": "..."} instead of scores;
    # aggregate should ignore it cleanly rather than crash.
    results = [
        _result(id="a", judge_scores={"realism": 4, "completeness": 4, "specificity": 4}),
        {
            "id": "b",
            "schema": {"ok": True, "msg": "ok"},
            "coverage": {"recall": 1.0, "missing": []},
            "business_rules": {"passed": 7, "total": 7, "details": []},
            "judge": {"error": "rate limited"},
            "task_count": 3,
            "total_hours": 50,
        },
    ]
    agg = aggregate(results)
    # Only the first contributed scores
    assert agg["judge_avg"]["realism"] == 4


def test_render_markdown_includes_run_metadata_and_per_example_rows():
    results = [
        _result(id="case_x", judge_scores={"realism": 4, "completeness": 5, "specificity": 3}),
    ]
    agg = aggregate(results)
    md = render_markdown(agg, results, model="gpt-4o-mini", run_id="run-xyz")
    assert "run-xyz" in md
    assert "gpt-4o-mini" in md
    assert "case_x" in md
    assert "Aggregate scores" in md
    assert "Per-example" in md


def test_render_markdown_lists_failures():
    failing = _result(id="case_fail", schema_ok=False, recall=0.4, rules_passed=4, rules_total=7)
    failing["business_rules"]["details"] = [
        {"name": "hours_consistent", "ok": False, "msg": "drift 30%"},
    ]
    failing["coverage"]["missing"] = ["training", "qa"]
    md = render_markdown(aggregate([failing]), [failing], model="gpt-4o-mini", run_id="r1")
    assert "case_fail" in md
    assert "drift 30%" in md
    assert "training" in md


def test_render_markdown_says_none_when_no_failures():
    passing = _result(id="case_ok")
    md = render_markdown(aggregate([passing]), [passing], model="gpt-4o-mini", run_id="r1")
    assert "_None._" in md
