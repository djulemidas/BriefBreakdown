import argparse
import json
import os
import statistics as stats
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from brief_breakdown.generator import generate_plan
from brief_breakdown.tracing import new_run_id
from evals.checks.business_rules import run_business_rules
from evals.checks.coverage_check import coverage
from evals.checks.llm_judge import judge
from evals.checks.schema_check import check_schema

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "dataset" / "golden.jsonl"
REPORTS = ROOT / "evals" / "reports"

console = Console()


def load_dataset() -> list[dict]:
    with DATASET.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate_one(case: dict, *, skip_judge: bool, run_id: str) -> dict:
    brief = case["brief"]
    required = case.get("required_signals", [])

    plan = generate_plan(brief, run_id=run_id)
    raw = plan.model_dump()

    schema_ok, schema_msg = check_schema(raw)
    recall, missing = coverage(plan, required)
    rules = run_business_rules(plan)
    rules_passed = sum(1 for _, ok, _ in rules if ok)

    verdict = None
    if not skip_judge:
        try:
            verdict = judge(brief, plan, run_id=run_id).model_dump()
        except Exception as e:
            verdict = {"error": str(e)}

    return {
        "id": case["id"],
        "schema": {"ok": schema_ok, "msg": schema_msg},
        "coverage": {"recall": recall, "missing": missing},
        "business_rules": {
            "passed": rules_passed,
            "total": len(rules),
            "details": [{"name": n, "ok": ok, "msg": msg} for n, ok, msg in rules],
        },
        "judge": verdict,
        "task_count": len(plan.tasks),
        "total_hours": plan.estimated_total_hours,
    }


def aggregate(results: list[dict]) -> dict:
    n = len(results)
    schema_pass = sum(1 for r in results if r["schema"]["ok"])
    recalls = [r["coverage"]["recall"] for r in results]
    rules_pass_rate = stats.mean(
        r["business_rules"]["passed"] / r["business_rules"]["total"] for r in results
    )

    judges = [r["judge"] for r in results if r["judge"] and "scores" in r["judge"]]
    judge_avg = {}
    if judges:
        for dim in ("realism", "completeness", "specificity"):
            judge_avg[dim] = stats.mean(j["scores"][dim] for j in judges)

    return {
        "n": n,
        "schema_pass_rate": schema_pass / n,
        "coverage_mean_recall": stats.mean(recalls) if recalls else 0,
        "business_rules_pass_rate": rules_pass_rate,
        "judge_avg": judge_avg,
    }


def render_console(agg: dict, results: list[dict]) -> None:
    console.rule("Evals summary")
    console.print(f"examples:        {agg['n']}")
    console.print(f"schema:          {agg['schema_pass_rate']:.0%}")
    console.print(f"coverage recall: {agg['coverage_mean_recall']:.2f}")
    console.print(f"business rules:  {agg['business_rules_pass_rate']:.0%}")
    if agg["judge_avg"]:
        ja = agg["judge_avg"]
        console.print(
            f"judge:           realism {ja['realism']:.2f} / "
            f"completeness {ja['completeness']:.2f} / "
            f"specificity {ja['specificity']:.2f}"
        )

    failures = [
        r
        for r in results
        if not r["schema"]["ok"]
        or r["coverage"]["recall"] < 1.0
        or r["business_rules"]["passed"] < r["business_rules"]["total"]
    ]
    if failures:
        console.rule("Failures")
        for r in failures:
            console.print(f"[bold]{r['id']}[/bold]")
            if not r["schema"]["ok"]:
                console.print(f"  schema: {r['schema']['msg']}")
            if r["coverage"]["recall"] < 1.0:
                console.print(f"  missing signals: {r['coverage']['missing']}")
            for d in r["business_rules"]["details"]:
                if not d["ok"]:
                    console.print(f"  rule [{d['name']}]: {d['msg']}")


def render_markdown(agg: dict, results: list[dict], *, model: str, run_id: str) -> str:
    lines: list[str] = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"# Eval report — {ts}")
    lines.append("")
    lines.append(f"- run id: `{run_id}`")
    lines.append(f"- model: `{model}`")
    lines.append(f"- examples: {agg['n']}")
    lines.append("")
    lines.append("## Aggregate scores")
    lines.append("")
    lines.append(f"| dimension | score |")
    lines.append(f"|-----------|-------|")
    lines.append(f"| schema pass rate | {agg['schema_pass_rate']:.0%} |")
    lines.append(f"| coverage mean recall | {agg['coverage_mean_recall']:.2f} |")
    lines.append(f"| business rules pass rate | {agg['business_rules_pass_rate']:.0%} |")
    if agg["judge_avg"]:
        ja = agg["judge_avg"]
        lines.append(f"| judge — realism | {ja['realism']:.2f} / 5 |")
        lines.append(f"| judge — completeness | {ja['completeness']:.2f} / 5 |")
        lines.append(f"| judge — specificity | {ja['specificity']:.2f} / 5 |")
    lines.append("")
    lines.append("## Per-example")
    lines.append("")
    lines.append("| id | tasks | hours | schema | coverage | rules | realism | comp | spec |")
    lines.append("|----|-------|-------|--------|----------|-------|---------|------|------|")
    for r in results:
        sc = r["judge"]["scores"] if (r["judge"] and "scores" in r["judge"]) else {}
        lines.append(
            f"| {r['id']} | {r['task_count']} | {r['total_hours']} | "
            f"{'ok' if r['schema']['ok'] else 'FAIL'} | "
            f"{r['coverage']['recall']:.2f} | "
            f"{r['business_rules']['passed']}/{r['business_rules']['total']} | "
            f"{sc.get('realism', '-')} | {sc.get('completeness', '-')} | {sc.get('specificity', '-')} |"
        )
    lines.append("")
    lines.append("## Failures (non-judge)")
    lines.append("")
    any_fail = False
    for r in results:
        problems = []
        if not r["schema"]["ok"]:
            problems.append(f"schema: {r['schema']['msg']}")
        if r["coverage"]["recall"] < 1.0:
            problems.append(f"missing signals: {r['coverage']['missing']}")
        for d in r["business_rules"]["details"]:
            if not d["ok"]:
                problems.append(f"rule [{d['name']}]: {d['msg']}")
        if problems:
            any_fail = True
            lines.append(f"### {r['id']}")
            for p in problems:
                lines.append(f"- {p}")
            lines.append("")
    if not any_fail:
        lines.append("_None._")
        lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-judge", action="store_true", help="Skip the LLM-as-judge dimension (saves tokens).")
    parser.add_argument("--limit", type=int, help="Run only the first N examples.")
    args = parser.parse_args()

    cases = load_dataset()
    if args.limit:
        cases = cases[: args.limit]

    run_id = new_run_id()
    console.print(f"Running {len(cases)} examples (run_id={run_id})")

    results = []
    for i, c in enumerate(cases, 1):
        console.print(f"  [{i}/{len(cases)}] {c['id']}")
        results.append(evaluate_one(c, skip_judge=args.no_judge, run_id=run_id))

    agg = aggregate(results)
    render_console(agg, results)

    REPORTS.mkdir(parents=True, exist_ok=True)
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    md = render_markdown(agg, results, model=model, run_id=run_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    (REPORTS / f"{timestamp}.md").write_text(md, encoding="utf-8")
    (REPORTS / "latest.md").write_text(md, encoding="utf-8")
    (REPORTS / f"{timestamp}.json").write_text(
        json.dumps({"run_id": run_id, "model": model, "aggregate": agg, "results": results}, indent=2),
        encoding="utf-8",
    )

    console.print(f"\nReport: evals/reports/latest.md  (and {timestamp}.md / .json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
