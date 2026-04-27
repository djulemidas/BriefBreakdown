import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from brief_breakdown.generator import generate_plan
from brief_breakdown.schema import ProjectPlan

console = Console()


def render(plan: ProjectPlan) -> None:
    console.print(Panel(plan.project_summary, title="Project summary", border_style="cyan"))
    console.print(f"[bold]Estimated total hours:[/bold] {plan.estimated_total_hours}")
    console.print(f"[bold]Phases:[/bold] {', '.join(plan.phases)}\n")

    tasks = Table(title="Tasks", show_lines=False)
    for col in ("id", "phase", "role", "hours", "title", "depends_on"):
        tasks.add_column(col)
    for t in plan.tasks:
        tasks.add_row(
            t.id, t.phase, t.role, str(t.estimate_hours), t.title, ",".join(t.depends_on) or "-"
        )
    console.print(tasks)

    if plan.milestones:
        ms = Table(title="Milestones")
        ms.add_column("name")
        ms.add_column("phase")
        for m in plan.milestones:
            ms.add_row(m.name, m.phase)
        console.print(ms)

    if plan.risks:
        rk = Table(title="Risks")
        for col in ("severity", "risk", "mitigation"):
            rk.add_column(col)
        for r in plan.risks:
            rk.add_row(r.severity, r.risk, r.mitigation)
        console.print(rk)


def main() -> int:
    parser = argparse.ArgumentParser(prog="brief-breakdown")
    parser.add_argument("brief", nargs="?", help="Client brief text. If omitted, read from stdin.")
    parser.add_argument("--model", help="Override OPENAI_MODEL.")
    parser.add_argument("--out", type=Path, help="Write the plan as JSON to this path.")
    parser.add_argument("--quiet", action="store_true", help="Skip the pretty render; just emit JSON to stdout.")
    args = parser.parse_args()

    brief = args.brief or sys.stdin.read().strip()
    if not brief:
        parser.error("no brief provided (pass as argument or pipe via stdin)")

    plan = generate_plan(brief, model=args.model)

    if args.out:
        args.out.write_text(json.dumps(plan.model_dump(), indent=2), encoding="utf-8")

    if args.quiet:
        print(json.dumps(plan.model_dump(), indent=2))
    else:
        render(plan)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
