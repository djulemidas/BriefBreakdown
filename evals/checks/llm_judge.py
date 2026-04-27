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
