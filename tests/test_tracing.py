import json
import time

from brief_breakdown import tracing


def test_log_span_writes_one_jsonl_line(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "TRACE_DIR", tmp_path)

    run_id = "test-run-001"
    tracing.log_span(
        run_id,
        span="generate_plan",
        model="gpt-4o-mini",
        input_payload={"brief": "hello"},
        output_payload={"summary": "world"},
        latency_ms=42,
        usage={"prompt_tokens": 10, "completion_tokens": 5},
    )

    trace_file = tmp_path / f"{run_id}.jsonl"
    assert trace_file.exists()
    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["run_id"] == run_id
    assert record["span"] == "generate_plan"
    assert record["model"] == "gpt-4o-mini"
    assert record["latency_ms"] == 42
    assert record["usage"]["prompt_tokens"] == 10
    assert record["input"] == {"brief": "hello"}
    assert record["output"] == {"summary": "world"}
    assert "ts" in record


def test_log_span_appends_multiple_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(tracing, "TRACE_DIR", tmp_path)
    run_id = "test-run-002"

    for i in range(3):
        tracing.log_span(
            run_id,
            span=f"span-{i}",
            model="gpt-4o-mini",
            input_payload={"i": i},
            output_payload={"i": i},
            latency_ms=i,
        )

    trace_file = tmp_path / f"{run_id}.jsonl"
    lines = trace_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    spans = [json.loads(line)["span"] for line in lines]
    assert spans == ["span-0", "span-1", "span-2"]


def test_new_run_id_is_unique():
    a = tracing.new_run_id()
    b = tracing.new_run_id()
    assert a != b
    # format: timestamp + short uuid
    assert "-" in a


def test_span_timer_measures_elapsed():
    with tracing.span_timer() as t:
        time.sleep(0.01)
    assert t.elapsed_ms >= 5  # 10ms minus scheduling slack
