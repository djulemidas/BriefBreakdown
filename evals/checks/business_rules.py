"""Business-rule checks: pure-Python invariants the model output must satisfy.

These checks are the deterministic backbone of the eval suite. They run on the
parsed `ProjectPlan` and produce `(passed, message)` pairs. No LLM calls, no
network — they are fast, free, and reproducible. A regression here is almost
always a real regression in the model output, not a flaky judge.

Each check answers a single question. The runner aggregates them so we can
report exactly which rule fired on which example, and the messages are written
to be skim-readable in the failure section of the eval report.
"""

from __future__ import annotations

from brief_breakdown.schema import Phase, ProjectPlan

HOUR_TOLERANCE = 0.10
MIN_MITIGATION_CHARS = 15
MAX_TASK_SHARE_OF_TOTAL = 0.40

# Canonical lifecycle order. Phases the model declares must appear as a
# subsequence of this list — discovery before design before build, etc.
CANONICAL_PHASE_ORDER: list[Phase] = [
    "discovery",
    "design",
    "build",
    "qa",
    "launch",
    "training",
]


def hours_consistent(plan: ProjectPlan, tolerance: float = HOUR_TOLERANCE) -> tuple[bool, str]:
    """Sum of per-task estimates must match the declared total within `tolerance`.

    What it tests: arithmetic consistency between the headline number a PM would
    quote and the breakdown that justifies it.
    How: sums `estimate_hours`, computes |sum - total| / total, fails if drift
    exceeds the tolerance (default 10%).
    Why: a plan whose tasks add up to half its declared total is internally
    incoherent and will mislead estimation downstream. This is the single
    cheapest signal of a sloppy generation.
    """
    total = plan.estimated_total_hours
    summed = sum(t.estimate_hours for t in plan.tasks)
    if total <= 0:
        return False, "estimated_total_hours must be positive"
    drift = abs(summed - total) / total
    if drift > tolerance:
        return False, f"task hours sum to {summed} vs declared total {total} (drift {drift:.0%})"
    return True, f"sum {summed} vs total {total} (drift {drift:.0%})"


def deps_resolve(plan: ProjectPlan) -> tuple[bool, str]:
    """Every `depends_on` id must reference a real task; no self-dependencies.

    What it tests: referential integrity of the task graph.
    How: collects the set of task ids, then iterates every dependency edge
    looking for unknown targets and self-loops (`t1 depends_on t1`).
    Why: a plan that references task ids the model invented is unusable in any
    UI that renders Gantt charts or critical paths. Catching this here is much
    cheaper than discovering it in production.
    """
    ids = {t.id for t in plan.tasks}
    bad = []
    for t in plan.tasks:
        for dep in t.depends_on:
            if dep not in ids:
                bad.append(f"{t.id}->{dep}")
            elif dep == t.id:
                bad.append(f"{t.id} self-dependency")
    if bad:
        return False, f"unresolved or self deps: {bad[:5]}"
    return True, "all deps resolve"


def no_dep_cycles(plan: ProjectPlan) -> tuple[bool, str]:
    """The task dependency graph must be a DAG (no cycles).

    What it tests: schedulability of the plan.
    How: depth-first traversal with a `visiting` set; if we re-enter a node on
    the active stack we report the cycle.
    Why: cyclic deps mean no task can start, so no scheduler can render the
    plan. Models occasionally produce `t1 -> t2 -> t1` when they reorder tasks
    after generating dependencies. Cheap to detect, cheap to fix in the prompt.
    """
    graph = {t.id: list(t.depends_on) for t in plan.tasks}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, stack: list[str]) -> list[str] | None:
        if node in visiting:
            i = stack.index(node) if node in stack else 0
            return stack[i:] + [node]
        if node in visited:
            return None
        visiting.add(node)
        stack.append(node)
        for nxt in graph.get(node, []):
            cycle = dfs(nxt, stack)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for n in graph:
        cycle = dfs(n, [])
        if cycle:
            return False, f"cycle: {' -> '.join(cycle)}"
    return True, "no cycles"


def each_phase_has_task(plan: ProjectPlan) -> tuple[bool, str]:
    """Every phase the plan declares must contain at least one task.

    What it tests: declared-vs-realised phases match.
    How: set difference between declared `phases` and the phases actually
    present on tasks.
    Why: a plan that announces a "training" phase but never assigns a task to
    it is misleading at a glance. This catches a common model failure where
    phases get listed aspirationally without being populated.
    """
    used = {t.phase for t in plan.tasks}
    declared = set(plan.phases)
    empty = declared - used
    if empty:
        return False, f"phases declared but empty: {sorted(empty)}"
    return True, "every declared phase has at least one task"


def phases_in_canonical_order(plan: ProjectPlan) -> tuple[bool, str]:
    """Declared phases must appear in canonical lifecycle order.

    What it tests: temporal sanity of the phase sequence.
    How: checks that `plan.phases` is a subsequence of
    `CANONICAL_PHASE_ORDER` (= discovery, design, build, qa, launch, training).
    Skipping a phase is fine; reordering is not.
    Why: a plan that puts "build" before "discovery" is either nonsense or a
    sign the model is hallucinating phase membership. Canonical order is the
    cheapest readable proxy for "did the model think about the lifecycle?".
    Limitation: this is a domain-specific assumption — agencies that operate
    differently would override `CANONICAL_PHASE_ORDER`.
    """
    declared = list(plan.phases)
    canonical_index = {p: i for i, p in enumerate(CANONICAL_PHASE_ORDER)}
    indices = [canonical_index[p] for p in declared if p in canonical_index]
    if indices != sorted(indices):
        return False, f"phases out of canonical order: declared={declared}"
    return True, f"phases in canonical order: {declared}"


def no_monolithic_task(
    plan: ProjectPlan,
    max_share: float = MAX_TASK_SHARE_OF_TOTAL,
) -> tuple[bool, str]:
    """No single task may consume more than `max_share` of the total hours.

    What it tests: granularity of the breakdown.
    How: compares each task's `estimate_hours` against `estimated_total_hours`
    and fails if any one exceeds the threshold (default 40%).
    Why: a "build the entire app — 200h" task is technically a plan, but it
    isn't a *breakdown*. This forces the generator to decompose work, which is
    the actual product value. Tunable: tighten to 25% to push for finer-grained
    plans, loosen to 50% if monolithic blocks are acceptable.
    """
    total = plan.estimated_total_hours
    if total <= 0:
        return False, "estimated_total_hours must be positive"
    offenders = [
        (t.id, t.estimate_hours, t.estimate_hours / total)
        for t in plan.tasks
        if t.estimate_hours / total > max_share
    ]
    if offenders:
        worst = max(offenders, key=lambda x: x[2])
        return False, f"task {worst[0]} = {worst[1]}h ({worst[2]:.0%} of total > {max_share:.0%})"
    return True, f"no task exceeds {max_share:.0%} of total"


def risks_have_substantive_mitigation(
    plan: ProjectPlan, min_chars: int = MIN_MITIGATION_CHARS
) -> tuple[bool, str]:
    """Every risk must come with a non-trivial mitigation.

    What it tests: usefulness of the risk register.
    How: counts characters in each `risk.mitigation` after stripping
    whitespace; fails if any is shorter than `min_chars` (default 15).
    Why: Pydantic only enforces presence, not quality. Models will sometimes
    return mitigations like "tbd" or "monitor" that satisfy the schema but
    add no information. The threshold is intentionally low — we are catching
    obvious garbage, not grading prose.
    Limitation: a 14-character but excellent mitigation would fail; a
    15-character but useless one would pass. The judge dimension is where we
    actually grade content quality.
    """
    if not plan.risks:
        return True, "no risks declared"
    bad = [
        (i, r.mitigation.strip())
        for i, r in enumerate(plan.risks)
        if len(r.mitigation.strip()) < min_chars
    ]
    if bad:
        return False, f"{len(bad)} risk(s) with mitigation under {min_chars} chars: {bad[:3]}"
    return True, f"all {len(plan.risks)} mitigations >= {min_chars} chars"


ALL_RULES = [
    ("hours_consistent", hours_consistent),
    ("deps_resolve", deps_resolve),
    ("no_dep_cycles", no_dep_cycles),
    ("each_phase_has_task", each_phase_has_task),
    ("phases_in_canonical_order", phases_in_canonical_order),
    ("no_monolithic_task", no_monolithic_task),
    ("risks_have_substantive_mitigation", risks_have_substantive_mitigation),
]


def run_business_rules(plan: ProjectPlan) -> list[tuple[str, bool, str]]:
    """Run every registered rule and return `(name, passed, message)` tuples.

    The runner consumes this list directly and reports per-rule pass/fail in
    the eval report. Order of rules in `ALL_RULES` is preserved so the report
    reads the same across runs.
    """
    return [(name, *fn(plan)) for name, fn in ALL_RULES]
