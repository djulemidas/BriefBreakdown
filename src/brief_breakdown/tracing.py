import atexit
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

TRACE_DIR = Path(os.getenv("BRIEF_BREAKDOWN_TRACE_DIR", "traces"))

# ---------------------------------------------------------------------------
# Langfuse lazy singleton
# ---------------------------------------------------------------------------

_lf = None
_lf_checked = False


def get_langfuse_client():
    """Return a live Langfuse client, or None if unconfigured or package absent."""
    global _lf, _lf_checked
    if _lf_checked:
        return _lf
    _lf_checked = True
    if not os.getenv("LANGFUSE_SECRET_KEY"):
        return None
    try:
        from langfuse import Langfuse  # noqa: PLC0415

        _lf = Langfuse(
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
        atexit.register(_lf.flush)
    except ImportError:
        pass  # langfuse extra not installed
    return _lf


# ---------------------------------------------------------------------------
# Local JSONL helpers
# ---------------------------------------------------------------------------


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
    session_id: str | None = None,
    trace_name: str | None = None,
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

    lf = get_langfuse_client()
    if lf is None:
        return

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(milliseconds=latency_ms)
    trace = lf.trace(id=run_id, name=trace_name or span, session_id=session_id)
    trace.generation(
        name=span,
        model=model,
        input=input_payload,
        output=output_payload,
        usage={
            "input": (usage or {}).get("prompt_tokens"),
            "output": (usage or {}).get("completion_tokens"),
            "unit": "TOKENS",
        },
        start_time=start_time,
        end_time=end_time,
    )


class span_timer:
    def __enter__(self):
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.elapsed_ms = int((time.perf_counter() - self.t0) * 1000)
