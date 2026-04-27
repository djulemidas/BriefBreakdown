import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

TRACE_DIR = Path(os.getenv("BRIEF_BREAKDOWN_TRACE_DIR", "traces"))


def _trace_path(run_id: str) -> Path:
    TRACE_DIR.mkdir(parents=True, exist_ok=True)
    return TRACE_DIR / f"{run_id}.jsonl"


def new_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    return f"{ts}-{uuid.uuid4().hex[:6]}"


def log_span(
    run_id: str,
    span: str,
    *,
    model: str,
    input_payload: object,
    output_payload: object,
    latency_ms: int,
    usage: dict | None = None,
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "span": span,
        "model": model,
        "latency_ms": latency_ms,
        "usage": usage or {},
        "input": input_payload,
        "output": output_payload,
    }
    with _trace_path(run_id).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


class span_timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = int((time.perf_counter() - self.t0) * 1000)
