from brief_breakdown.schema import ProjectPlan
from evals.checks.business_rules import (
    HOUR_TOLERANCE,
    deps_resolve,
    each_phase_has_task,
    hours_consistent,
    no_dep_cycles,
    no_monolithic_task,
    phases_in_canonical_order,
    risks_have_substantive_mitigation,
    run_business_rules,
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


# -- hours_consistent -----------------------------------------------------


def test_hours_consistent_passes():
    ok, _ = hours_consistent(make_plan())
    assert ok


def test_hours_drift_caught():
    plan = make_plan(estimated_total_hours=100)
    ok, msg = hours_consistent(plan)
    assert not ok
    assert "drift" in msg


def test_hours_at_tolerance_boundary_passes():
    # total=100 with task sum=110 -> exactly 10% drift, within default tolerance
    plan = make_plan(estimated_total_hours=100)
    plan.tasks[1].estimate_hours = 100  # sum = 5+100+5 = 110
    ok, _ = hours_consistent(plan, tolerance=HOUR_TOLERANCE)
    assert ok


def test_hours_just_over_tolerance_fails():
    plan = make_plan(estimated_total_hours=100)
    plan.tasks[1].estimate_hours = 106  # sum = 116, drift 16%
    ok, _ = hours_consistent(plan, tolerance=HOUR_TOLERANCE)
    assert not ok


def test_hours_custom_tolerance():
    # 30% drift would fail default 10% but pass with 50% tolerance
    plan = make_plan(estimated_total_hours=100)
    plan.tasks[1].estimate_hours = 125  # sum = 135, drift 35%
    assert not hours_consistent(plan, tolerance=0.10)[0]
    assert hours_consistent(plan, tolerance=0.50)[0]


# -- deps_resolve ---------------------------------------------------------


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


# -- no_dep_cycles --------------------------------------------------------


def test_no_dep_cycles_passes():
    ok, _ = no_dep_cycles(make_plan())
    assert ok


def test_dep_cycle_caught():
    plan = make_plan()
    plan.tasks[0].depends_on = ["t3"]
    ok, msg = no_dep_cycles(plan)
    assert not ok
    assert "cycle" in msg


def test_long_dep_cycle_caught():
    # t1 -> t2 -> t3 -> t1
    plan = make_plan()
    plan.tasks[0].depends_on = ["t3"]
    plan.tasks[1].depends_on = ["t1"]
    plan.tasks[2].depends_on = ["t2"]
    ok, _ = no_dep_cycles(plan)
    assert not ok


# -- each_phase_has_task --------------------------------------------------


def test_each_phase_populated():
    ok, _ = each_phase_has_task(make_plan())
    assert ok


def test_empty_phase_caught():
    plan = make_plan(phases=["discovery", "build", "qa", "launch"])
    ok, msg = each_phase_has_task(plan)
    assert not ok
    assert "launch" in msg


# -- phases_in_canonical_order --------------------------------------------


def test_canonical_order_passes():
    plan = make_plan(phases=["discovery", "build", "qa"])
    ok, _ = phases_in_canonical_order(plan)
    assert ok


def test_canonical_order_with_skips_passes():
    # skipping design and launch is fine; reordering is not
    plan = make_plan(phases=["discovery", "qa", "training"])
    plan.tasks[1].phase = "qa"
    plan.tasks[2].phase = "training"
    ok, _ = phases_in_canonical_order(plan)
    assert ok


def test_canonical_order_violation_caught():
    plan = make_plan(phases=["build", "discovery", "qa"])
    ok, msg = phases_in_canonical_order(plan)
    assert not ok
    assert "canonical" in msg


# -- no_monolithic_task ---------------------------------------------------


def test_no_monolithic_task_passes_on_balanced_plan():
    # default plan has 5/30, 20/30, 5/30 -> 67% on t2, fails default 40%
    # so first construct a balanced plan
    plan = make_plan(estimated_total_hours=40)
    plan.tasks[0].estimate_hours = 10
    plan.tasks[1].estimate_hours = 15
    plan.tasks[2].estimate_hours = 15
    ok, _ = no_monolithic_task(plan)
    assert ok


def test_monolithic_task_caught():
    # default plan: t2 = 20/30 = 67% -> fails 40% threshold
    ok, msg = no_monolithic_task(make_plan())
    assert not ok
    assert "t2" in msg


def test_monolithic_threshold_tunable():
    # the default plan passes when threshold is loosened to 80%
    ok, _ = no_monolithic_task(make_plan(), max_share=0.80)
    assert ok


# -- risks_have_substantive_mitigation ------------------------------------


def test_no_risks_passes_trivially():
    ok, _ = risks_have_substantive_mitigation(make_plan())
    assert ok


def test_substantive_mitigation_passes():
    plan = make_plan(
        risks=[
            {
                "risk": "Tight launch deadline",
                "severity": "medium",
                "mitigation": "Lock scope by week 6 and stage features behind a flag.",
            }
        ]
    )
    ok, _ = risks_have_substantive_mitigation(plan)
    assert ok


def test_short_mitigation_caught():
    plan = make_plan(
        risks=[{"risk": "Risk A", "severity": "low", "mitigation": "tbd"}]
    )
    ok, msg = risks_have_substantive_mitigation(plan)
    assert not ok
    assert "under" in msg


def test_whitespace_only_mitigation_caught():
    plan = make_plan(
        risks=[{"risk": "Risk A", "severity": "low", "mitigation": "        "}]
    )
    ok, _ = risks_have_substantive_mitigation(plan)
    assert not ok


# -- runner ---------------------------------------------------------------


def test_run_business_rules_returns_all_named_rules():
    results = run_business_rules(make_plan())
    names = [r[0] for r in results]
    assert "hours_consistent" in names
    assert "deps_resolve" in names
    assert "no_dep_cycles" in names
    assert "each_phase_has_task" in names
    assert "phases_in_canonical_order" in names
    assert "no_monolithic_task" in names
    assert "risks_have_substantive_mitigation" in names
    # tuple shape is (name, ok, msg)
    for name, ok, msg in results:
        assert isinstance(name, str)
        assert isinstance(ok, bool)
        assert isinstance(msg, str)


# -- coverage -------------------------------------------------------------


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


def test_coverage_empty_signals_is_full_recall():
    # No signals to find -> trivially perfect recall, no missing.
    plan = make_plan()
    recall, missing = coverage(plan, [])
    assert recall == 1.0
    assert missing == []


def test_coverage_is_case_insensitive():
    plan = make_plan()
    plan.tasks[0].title = "Kickoff WORKSHOP"
    recall, _ = coverage(plan, ["kickoff", "workshop"])
    assert recall == 1.0


def test_coverage_matches_in_description_and_summary():
    plan = make_plan(project_summary="Shopify Plus migration with Klaviyo")
    plan.tasks[0].description = "Audit existing Magento storefront"
    recall, missing = coverage(plan, ["shopify", "klaviyo", "magento"])
    assert recall == 1.0
    assert missing == []


def test_coverage_matches_in_risks():
    plan = make_plan(
        risks=[
            {
                "risk": "Magento custom attributes may not map to Shopify metafields",
                "severity": "high",
                "mitigation": "Run a test export in week 1 and adjust the mapping plan.",
            }
        ]
    )
    recall, _ = coverage(plan, ["metafields"])
    assert recall == 1.0


def test_coverage_multi_word_signal():
    # Multi-word signals must appear contiguously.
    plan = make_plan()
    plan.tasks[0].description = "We will run a case study during discovery"
    assert coverage(plan, ["case study"])[0] == 1.0
    plan.tasks[0].description = "Studies of various cases will be reviewed"
    assert coverage(plan, ["case study"])[0] == 0.0
