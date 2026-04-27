import os
from dotenv import load_dotenv
from openai import OpenAI

from brief_breakdown.prompts import SYSTEM_PROMPT
from brief_breakdown.schema import ProjectPlan
from brief_breakdown.tracing import log_span, new_run_id, span_timer

load_dotenv()

DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def generate_plan(
    brief: str,
    *,
    model: str | None = None,
    run_id: str | None = None,
) -> ProjectPlan:
    """Turn an agency brief into a structured ProjectPlan via OpenAI structured outputs."""
    model = model or DEFAULT_MODEL
    run_id = run_id or new_run_id()
    client = OpenAI()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Client brief:\n\n{brief}"},
    ]

    with span_timer() as t:
        completion = client.chat.completions.parse(
            model=model,
            messages=messages,
            response_format=ProjectPlan,
        )

    plan = completion.choices[0].message.parsed
    if plan is None:
        raise RuntimeError(f"Model refused or returned no parsed output: {completion.choices[0].message}")

    usage = (
        {
            "prompt_tokens": completion.usage.prompt_tokens,
            "completion_tokens": completion.usage.completion_tokens,
            "total_tokens": completion.usage.total_tokens,
        }
        if completion.usage
        else {}
    )

    log_span(
        run_id,
        span="generate_plan",
        model=model,
        input_payload={"brief": brief},
        output_payload=plan.model_dump(),
        latency_ms=t.elapsed_ms,
        usage=usage,
    )

    return plan
