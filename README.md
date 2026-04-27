# BriefBreakdown

Turns a free-text agency project brief into a structured project plan (tasks, roles, estimates, phases, milestones, risks) using the OpenAI API. Ships with a four-dimension automated evaluation suite.

## What it shows

- **OpenAI structured outputs.** Pydantic-typed `ProjectPlan` schema; the model can't return invalid JSON, can't invent unknown roles or phases.
- **Local Langfuse-shaped tracing.** Every LLM call (generation + judge) writes a JSONL span with model, latency, token usage, input, output. Swapping in real Langfuse is a one-function change.
- **Automated evals across four independent dimensions.** Cheap deterministic checks first; expensive LLM-as-judge last.

## Quick start

```bash
cp .env.example .env
# edit .env: set OPENAI_API_KEY (and optionally OPENAI_MODEL, default gpt-4o-mini)

python -m venv .venv
. .venv/Scripts/activate    # on Windows; on Unix: source .venv/bin/activate
pip install -e ".[dev]"

# Generate a plan from a brief
python -m brief_breakdown "B2B SaaS company needs a brand refresh: new logo, type system, marketing site on Webflow. 10 weeks, $40k."

# Run the eval suite (uses the 12-example golden dataset)
python -m evals.runners.run_evals

# Faster (skips the LLM-as-judge dimension to save tokens)
python -m evals.runners.run_evals --no-judge

# Run pure-Python unit tests (no OpenAI calls)
pytest
```

## Eval dimensions

The runner produces a Markdown report at `evals/reports/latest.md` plus a JSON dump and a timestamped copy.

### 1. Schema validity (`evals/checks/schema_check.py`)
Pydantic parse must succeed. With OpenAI's structured outputs this is essentially a tripwire — if it ever fails, something has changed in the SDK or the schema and we want to know loudly. Pass/fail per example.

### 2. Coverage (`evals/checks/coverage_check.py`)
Each golden example is hand-labeled with `required_signals` (e.g., a Shopify migration must mention "magento", "klaviyo", "training"). The check is a case-insensitive substring scan over task titles, descriptions, the project summary, and risk text. Reports recall (% found). Cheap, deterministic, surprisingly effective at catching omissions.

### 3. Business rules (`evals/checks/business_rules.py`)
Pure-Python invariants. No LLM calls, no flakiness:
- Sum of task hours must be within ~10% of declared total
- Every `depends_on` id must resolve to a real task; no self-deps
- No dependency cycles (DFS)
- Every declared phase must have at least one task

### 4. LLM-as-judge (`evals/checks/llm_judge.py`)
A separate `gpt-4o-mini` call grades the plan 1–5 on three dimensions with rationale:
- **realism** — are the hour estimates and phase mix plausible?
- **completeness** — are all reasonable workstreams covered?
- **specificity** — do tasks reference the brief, or is it generic boilerplate?

The judge returns structured JSON via Pydantic so scores are aggregable.

### Why these four dimensions?

Defense in depth, ordered cheapest-first:

1. Schema → catches malformed output, near-zero cost.
2. Coverage → catches major omissions, deterministic.
3. Business rules → catches internal inconsistency, deterministic.
4. Judge → catches subjective quality issues that the first three miss.

Each layer fails fast and tells you exactly which dimension regressed. Adding a new failure mode usually means adding a deterministic check, not a smarter judge.

## Known limitations

- **LLM-as-judge bias.** The judge may favor verbose plans or mirror its own style preferences. Calibrating against a human-labeled subset and rotating judge models would be the next step.
- **Coverage is keyword-based.** A semantically equivalent phrasing that doesn't match the literal token gets marked as missing. A small embedding-based check would help, but adds runtime cost and one more failure mode.
- **Small dataset.** 12 examples is enough to detect regressions during prompt iteration; a real production setup needs hundreds, versioned, with stratified slices (industry, project type, budget tier).
- **No regression gating yet.** In production this would run in CI with thresholds (e.g., fail PR if business rules pass rate drops below 95% or judge averages drop more than 0.3).

## Project layout

```
src/brief_breakdown/      # the AI feature itself
  schema.py               # Pydantic models — single source of truth for the output contract
  prompts.py              # system + judge prompts
  generator.py            # generate_plan() — structured-output OpenAI call
  tracing.py              # local JSONL spans (Langfuse-shaped)
  cli.py                  # python -m brief_breakdown "..."
evals/
  dataset/golden.jsonl    # 12 hand-curated (brief, required_signals) pairs
  checks/                 # the four eval dimensions
  runners/run_evals.py    # orchestrator → console summary + Markdown + JSON report
tests/                    # pytest unit tests, no LLM calls
```

## Production next steps

If this were a real production feature, the obvious next moves:
- Replace local JSONL tracing with Langfuse (`langfuse.trace()` swap).
- Version the dataset and store eval runs with git SHA + model version for trend analysis.
- CI gate: run `--no-judge` evals on every PR, full suite nightly, fail on regression > N%.
- Stratified slices: report scores per industry / project type to catch domain-specific regressions.
- Human calibration: have a delivery lead grade ~30 plans, compare against the judge, track agreement.
- For agentic versions: add trajectory evals (did the agent take a sensible path?), tool-call correctness, end-state checks.

## Security note

If you ever paste an API key into a chat or commit it to a repo, revoke it. This project reads `OPENAI_API_KEY` from `.env` (gitignored).
