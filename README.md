# BriefBreakdown

Turns a free-text agency project brief into a structured project plan (tasks, roles, estimates, phases, milestones, risks) using the OpenAI API. Ships with a multi-dimension automated evaluation suite designed to detect regressions during prompt or model changes.

## What it shows

- **OpenAI structured outputs.** Pydantic-typed `ProjectPlan` schema; the model can't return invalid JSON, can't invent unknown roles or phases.
- **Local Langfuse-shaped tracing.** Every LLM call (generation + judge) writes a JSONL span with model, latency, token usage, input, output. Swapping in real Langfuse is a one-function change.
- **Four-layer evaluation suite.** Cheap deterministic checks first, expensive LLM-as-judge last. Each layer fails fast with a specific message.

## Quick start

```bash
cp .env.example .env
# edit .env: set OPENAI_API_KEY (and optionally OPENAI_MODEL, default gpt-4o-mini)

python -m venv .venv
. .venv/Scripts/activate    # on Windows; on Unix: source .venv/bin/activate
pip install -e ".[dev]"

# Generate a plan from a brief
python -m brief_breakdown "B2B SaaS company needs a brand refresh: new logo, type system, marketing site on Webflow. 10 weeks, $40k."

# Run the eval suite (uses the 15-example golden dataset)
python -m evals.runners.run_evals

# Faster (skips the LLM-as-judge dimension to save tokens)
python -m evals.runners.run_evals --no-judge

# Run pure-Python unit tests (no OpenAI calls)
pytest
```

---

## How the evaluations work

### The mental model

Evaluating an LLM feature isn't one job — it's at least three:

1. **Did the model produce the right *shape* of output?** Schema-level questions.
2. **Is the output internally consistent and structurally sane?** Invariant-level questions, answerable without an LLM.
3. **Is the output any good?** Quality-level questions that require judgement, where you either pay a human or pay a model to judge.

Mixing these into a single "score" hides which one regressed when something breaks. So the suite reports each dimension separately, and the runner orders them cheapest-first so you spend tokens (and time) on the subjective dimension only after the deterministic ones have passed.

### Pipeline

For each example in the golden dataset, the runner does this:

```
brief ──► generate_plan() ──► ProjectPlan (Pydantic)
                                  │
                                  ├──► [1] schema_check      (Pydantic parse)
                                  ├──► [2] coverage_check    (keyword recall)
                                  ├──► [3] business_rules    (7 invariants)
                                  └──► [4] llm_judge         (1-5 × 3 axes)
                                                │
                                                ▼
                          aggregate ──► console + markdown + json report
```

Every LLM call (the generation itself, plus the judge) is logged as a JSONL span under `traces/<run_id>.jsonl` so you can replay and inspect exactly what happened.

### The four dimensions in detail

#### 1. Schema validity — [`evals/checks/schema_check.py`](evals/checks/schema_check.py)

Pydantic parse against the `ProjectPlan` model. With OpenAI structured outputs this should be 100%; if it ever fails it's an SDK or schema regression and we want to know immediately. The runner uses this as a fast-fail gate before the more expensive checks try to read fields that may not exist.

#### 2. Coverage — [`evals/checks/coverage_check.py`](evals/checks/coverage_check.py)

Each golden example is hand-labeled with `required_signals`: short tokens that any sensible plan for that brief should mention (e.g., a Shopify migration brief expects `magento`, `shopify`, `klaviyo`, `training`). The check does a case-insensitive substring scan over the project summary, every task title and description, and every risk statement. It returns:

- **recall** — fraction of required signals found
- **missing** — the specific signals that didn't show up

Cheap, deterministic, and very effective at catching the most common failure mode: the model produces a plan that ignores the brief's specifics and reads like generic boilerplate. The dataset's signals are deliberately set so that mean recall in the **0.7-0.9** band is the realistic target — substring matching is too brittle for 1.0 to be a reasonable goal.

#### 3. Business rules — [`evals/checks/business_rules.py`](evals/checks/business_rules.py)

Seven pure-Python invariants. No LLM calls, no flakiness, run on every example:

| rule | what it tests |
|------|---------------|
| `hours_consistent` | Sum of `task.estimate_hours` is within ±10% of `estimated_total_hours`. |
| `deps_resolve` | Every `depends_on` id refers to a real task. No self-dependencies. |
| `no_dep_cycles` | The dependency graph is a DAG (DFS-based detection). |
| `each_phase_has_task` | Every phase the plan declares contains at least one task. |
| `phases_in_canonical_order` | Declared phases are a subsequence of `discovery → design → build → qa → launch → training`. |
| `no_monolithic_task` | No single task consumes more than 40% of the total hours. |
| `risks_have_substantive_mitigation` | Every risk's mitigation has at least 15 non-whitespace chars. |

These exist because each catches a real failure mode I've seen in early generations: numbers that don't add up, dangling dependencies, accidental cycles when the model reorders tasks, declared phases the model forgets to populate, "just one giant 'build the app' task", and the dreaded mitigation field that says `tbd`.

The thresholds are tunable — `MAX_TASK_SHARE_OF_TOTAL`, `MIN_MITIGATION_CHARS`, `HOUR_TOLERANCE` are module-level constants. Tightening them pushes the prompt harder; loosening them is fine if the trade-off is intentional.

#### 4. LLM-as-judge — [`evals/checks/llm_judge.py`](evals/checks/llm_judge.py)

A separate `gpt-4o-mini` (configurable via `OPENAI_JUDGE_MODEL`) call sees the brief and the JSON plan, then returns a `JudgeVerdict` with three integer scores (1-5) and a one-sentence rationale per dimension:

- **realism** — are the hour estimates and phase mix plausible?
- **completeness** — are all reasonable workstreams covered (kickoff, build, QA, launch, training if implied)?
- **specificity** — do tasks reference the brief's specifics, or is it generic boilerplate that could fit any project?

The judge prompt is in [`src/brief_breakdown/prompts.py`](src/brief_breakdown/prompts.py). It returns Pydantic-typed structured output so the scores aggregate cleanly across runs and you can plot trends without parsing free text.

### Reading a failure

When the suite reports a failure, the layers tell you where to look:

| failing dimension | what it usually means |
|-------------------|-----------------------|
| schema | the SDK or the `ProjectPlan` schema changed; regenerate before doing anything else |
| coverage | the prompt isn't pulling enough specifics from the brief; either tighten the prompt or accept lower recall |
| business rules | a structural bug — usually fixable with one prompt tweak that shows up in every regenerated example |
| judge only | a quality regression that's hard to pin down; check the rationale fields and look for patterns across examples |

If schema fails, ignore everything else for that example — coverage and business rules will be reading dict keys that don't exist.

### Philosophy: deterministic-first

Every time we replace a deterministic check with a judge call we lose:

- reproducibility (judge scores fluctuate run-to-run)
- speed (a deterministic check is microseconds; a judge call is seconds)
- trust (a judge can be biased; an integer comparison can't)

So the policy is: **whenever a failure mode can be expressed as a deterministic invariant, encode it as one**, and only fall back to the judge for things that genuinely require taste. Each new business rule retires one piece of judge work and makes the suite faster, cheaper, and more reliable.

### Known limitations

- **LLM-as-judge bias.** The judge may favor verbose outputs or mirror style preferences from its own family. Mitigations: rotate judge models, calibrate against a human-labeled subset, track judge-vs-human agreement over time.
- **Variance.** The same plan judged twice will produce slightly different scores. For trend work, run the suite N times and report mean ± stddev rather than single-run numbers.
- **Coverage is keyword-based.** A semantically equivalent phrasing that doesn't match the literal token gets marked as missing. An embedding-based variant would handle paraphrase, at the cost of one more dependency and another failure mode.
- **Small dataset.** 15 hand-curated examples is enough to detect regressions during prompt iteration but isn't statistically meaningful at production scale. Real deployment would need hundreds, versioned, with stratified slices (industry, project type, budget tier).
- **No regression gating yet.** In production this would run in CI with concrete thresholds: fail PR if `schema_pass_rate < 1.0`, `business_rules_pass_rate < 0.95`, or any judge average drops by more than ~0.3 versus the rolling baseline.

---

## Unit tests

Three pytest modules cover the pure-Python parts of the system. None hit the OpenAI API, so they run in ~1s and are safe to wire into pre-commit / CI:

- [`tests/test_schema.py`](tests/test_schema.py) — Pydantic model validation: invalid roles, phases, severities, missing required fields, hour bounds, default values.
- [`tests/test_business_rules.py`](tests/test_business_rules.py) — every business rule (happy path + at least one failure mode), tolerance-parameter behaviour, coverage check edge cases (empty signals, case-insensitivity, multi-word, matches in summary/description/risk).
- [`tests/test_runner.py`](tests/test_runner.py) — `aggregate()` and `render_markdown()` against handwritten result fixtures, including the case where a judge call errored out and recorded `{"error": ...}` instead of scores.
- [`tests/test_tracing.py`](tests/test_tracing.py) — `log_span()` writes well-formed JSONL, appends across multiple calls, `new_run_id()` returns unique ids, `span_timer` measures elapsed time.

Run them with:

```bash
pytest          # 55 tests, ~1s
pytest -v       # show every test name
```

## Project layout

```
src/brief_breakdown/      # the AI feature itself
  schema.py               # Pydantic models — single source of truth for the output contract
  prompts.py              # system + judge prompts
  generator.py            # generate_plan() — structured-output OpenAI call
  tracing.py              # local JSONL spans (Langfuse-shaped)
  cli.py                  # python -m brief_breakdown "..."
evals/
  dataset/golden.jsonl    # 15 hand-curated (brief, required_signals) pairs
  checks/                 # the four eval dimensions, each with module + function docstrings
  runners/run_evals.py    # orchestrator → console summary + Markdown + JSON report
tests/                    # pytest unit tests, no LLM calls
```

## Production next steps

If this were a real production feature, the obvious next moves:

- **Tracing.** Replace local JSONL with Langfuse (`langfuse.trace()` swap). The current trace shape is intentionally Langfuse-compatible.
- **Dataset versioning.** Store golden examples in a versioned table or git-tracked yaml. Tag each eval run with the dataset version + model version + git SHA so you can plot score trends over time and pinpoint when a regression entered.
- **CI gating.** Run `--no-judge` evals on every PR (cheap and deterministic), full suite nightly. Fail PR if any deterministic dimension regresses; alert if judge averages drop > 0.3 versus the rolling baseline.
- **Stratified slices.** Report aggregate scores per industry / project size / budget tier. A 5% overall drop might be a 30% drop on data-warehouse briefs and zero elsewhere — that's the regression you actually care about.
- **Human calibration.** Have a delivery lead grade ~30 plans by hand, compare to the judge, track inter-rater agreement. If agreement is low, the judge prompt is wrong, not the model.
- **Agentic extension.** For multi-step versions of this feature, add trajectory evals (did the agent take a sensible path?), tool-call correctness, and end-state checks against a fixture state.

## Security note

If you ever paste an API key into a chat or commit it to a repo, revoke it. This project reads `OPENAI_API_KEY` from `.env` (gitignored).
