"""LLM-as-judge: a separate model scores the plan on three subjective axes.

This is the most expensive and least deterministic dimension in the suite. We
run it last and keep its rubric narrow so the scores are aggregable across
runs. The judge returns Pydantic-typed structured output (1-5 integers plus
short rationales) rather than free text, which keeps trends visible over time.

Why have a judge at all when the deterministic checks above are cheaper?
Because realism, completeness, and specificity are not invariants — they are
quality signals. A plan can pass every business rule and still be terrible. A
judge approximates "would a delivery lead trust this?" without needing humans
in the loop on every iteration.

Known limitations (acknowledge them, don't pretend they aren't there):
  - Self-bias: the judge model may favor outputs from the same family.
    Mitigation: rotate judge models, or use a stronger model for judging.
  - Verbosity bias: longer outputs tend to score higher.
    Mitigation: keep the rubric explicit about specificity, not length.
  - Variance: judge scores fluctuate on identical inputs.
    Mitigation: run the suite N times and report mean + stddev for trend work.
"""

import json
import os
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, Field

from brief_breakdown.prompts import JUDGE_PROMPT
from brief_breakdown.schema import ProjectPlan
from brief_breakdown.tracing import log_span, span_timer

JUDGE_MODEL = os.getenv("OPENAI_JUDGE_MODEL", "gpt-4o-mini")

Score = Literal[1, 2, 3, 4, 5]


class JudgeScores(BaseModel):
    realism: Score = Field(description="1=wildly off, 5=plausible estimates and phase mix.")
    completeness: Score = Field(description="1=major gaps, 5=all reasonable workstreams covered.")
    specificity: Score = Field(description="1=generic, 5=tightly grounded in the brief.")


class JudgeVerdict(BaseModel):
    scores: JudgeScores
    realism_rationale: str
    completeness_rationale: str
    specificity_rationale: str


def judge(brief: str, plan: ProjectPlan, *, run_id: str, model: str | None = None) -> JudgeVerdict:
    """Score a plan on realism, completeness, and specificity (1-5 each).

    What it tests: subjective quality dimensions the deterministic checks
    cannot reach.
    How: a separate `gpt-4o-mini` (or `OPENAI_JUDGE_MODEL`) call sees the
    brief and the JSON plan, then returns a `JudgeVerdict` with three integer
    scores and a one-sentence rationale per dimension.
    Why: the rest of the suite catches what is broken; this catches what is
    merely bad.
    """
    model = model or JUDGE_MODEL
    client = OpenAI()

    plan_json = json.dumps(plan.model_dump(), indent=2)
    user = (
        f"BRIEF:\n{brief}\n\n"
        f"PLAN (JSON):\n{plan_json}\n\n"
        "Score the plan and provide a one-sentence rationale per dimension."
    )

    with span_timer() as t:
        completion = client.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": JUDGE_PROMPT},
                {"role": "user", "content": user},
            ],
            response_format=JudgeVerdict,
        )

    verdict = completion.choices[0].message.parsed
    if verdict is None:
        raise RuntimeError("judge returned no parsed output")

    log_span(
        run_id,
        span="llm_judge",
        model=model,
        input_payload={"brief": brief, "plan": plan.model_dump()},
        output_payload=verdict.model_dump(),
        latency_ms=t.elapsed_ms,
        usage=(
            {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
            }
            if completion.usage
            else {}
        ),
    )

    return verdict
