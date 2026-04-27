from brief_breakdown.schema import ProjectPlan

HOUR_TOLERANCE = 0.10


def hours_consistent(plan: ProjectPlan, tolerance: float = HOUR_TOLERANCE) -> tuple[bool, str]:
    total = plan.estimated_total_hours
    summed = sum(t.estimate_hours for t in plan.tasks)
    if total <= 0:
        return False, "estimated_total_hours must be positive"
    drift = abs(summed - total) / total
    if drift > tolerance:
        return False, f"task hours sum to {summed} vs declared total {total} (drift {drift:.0%})"
    return True, f"sum {summed} vs total {total} (drift {drift:.0%})"


def deps_resolve(plan: ProjectPlan) -> tuple[bool, str]:
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
    used = {t.phase for t in plan.tasks}
    declared = set(plan.phases)
    empty = declared - used
    if empty:
        return False, f"phases declared but empty: {sorted(empty)}"
    return True, "every declared phase has at least one task"


ALL_RULES = [
    ("hours_consistent", hours_consistent),
    ("deps_resolve", deps_resolve),
    ("no_dep_cycles", no_dep_cycles),
    ("each_phase_has_task", each_phase_has_task),
]


def run_business_rules(plan: ProjectPlan) -> list[tuple[str, bool, str]]:
    return [(name, *fn(plan)) for name, fn in ALL_RULES]
