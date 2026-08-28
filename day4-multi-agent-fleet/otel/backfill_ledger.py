"""
===============================================================================
 BACKFILL  —  the week's own ledgers, replayed onto the OpenTelemetry pipe
===============================================================================

    python otel/backfill_ledger.py

Reads, READ-ONLY, the run evidence the week already produced — the same
sources as the fleet view:

    fleet/records.jsonl                     (day 4: patterns + drift demo)
    ../day3-test-pipeline/ledger.csv     (day 3: generate + triage runs)

— and emits ONE OTLP SPAN PER RECORDED RUN, with its real timestamp, its
real duration, and its tokens/cost/outcome as attributes, into the Phoenix
project "fleet-week".

The point of the demo: the ledger came first, and it was enough. A record
you already wrote is one exporter away from any OTel backend — Phoenix
today, Grafana / Datadog / Azure Monitor tomorrow, because OTLP is the
standard pipe. Records first; visualization free.
===============================================================================
"""
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from phoenix.otel import register
from opentelemetry.trace import Status, StatusCode

HERE = Path(__file__).parent
ROOT = HERE.parent
WEEK = ROOT.parent                      # the "AI And Agents" folder

DAY3_DATE = "2026-08-27"                # ledger.csv stores time-of-day only

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def ns(dt):
    return int(dt.timestamp() * 1_000_000_000)


def emit(tracer, name, start_dt, seconds, attrs, failed=False):
    """One recorded run -> one span, at its REAL time with its REAL duration."""
    span = tracer.start_span(name, start_time=ns(start_dt), attributes=attrs)
    span.set_status(Status(StatusCode.ERROR if failed else StatusCode.OK))
    span.end(end_time=ns(start_dt) + int(max(seconds, 0.001) * 1e9))


def day4_records(tracer):
    p = ROOT / "fleet" / "records.jsonl"
    if not p.exists():
        return 0, "fleet/records.jsonl not found - skipped"
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        emit(tracer, r["agent"],
             datetime.strptime(r["ts"], "%Y-%m-%d %H:%M:%S"),
             r.get("seconds") or 0.5,
             {"openinference.span.kind": "AGENT",
              "llm.model_name": r["model"],
              "llm.token_count.prompt": r["input_tokens"],
              "llm.token_count.completion": r["output_tokens"],
              "llm.token_count.total": r["input_tokens"] + r["output_tokens"],
              "cost_usd": r["cost_usd"], "pattern": r["pattern"],
              "prompt_version": r["prompt_version"],
              "outcome": r["outcome"], "day": 4},
             failed=(r["outcome"] == "FAIL"))
        n += 1
    return n, None


def day3_ledger(tracer):
    p = WEEK / "day3-test-pipeline" / "ledger.csv"
    if not p.exists():
        return 0, "day3 ledger.csv not found - skipped"
    n = 0
    for r in csv.DictReader(p.open(encoding="utf-8")):
        ti, to = int(r["input_tokens"] or 0), int(r["output_tokens"] or 0)
        if ti + to == 0:
            continue                    # runner rows: machinery, no model
        emit(tracer, f"day3-{r['step']}",
             datetime.strptime(f"{DAY3_DATE} {r['ts']}", "%Y-%m-%d %H:%M:%S"),
             float(r["seconds"] or 1),
             {"openinference.span.kind": "AGENT",
              "llm.model_name": "gpt-5.4",
              "llm.token_count.prompt": ti,
              "llm.token_count.completion": to,
              "llm.token_count.total": ti + to,
              "cost_usd": float(r["cost_usd"] or 0),
              "note": r.get("note", ""), "day": 3})
        n += 1
    return n, None


def main():
    print("backfill — the week's ledgers, replayed as OTel spans\n")
    provider = register(project_name="fleet-week",
                        set_global_tracer_provider=False, verbose=False)
    tracer = provider.get_tracer("ledger-backfill")

    total = 0
    for source in (day4_records, day3_ledger):
        n, warn = source(tracer)
        total += n
        print(f"   {source.__doc__ or source.__name__:<14} "
              f"{warn or f'{n} runs -> {n} spans'}")
    provider.force_flush()

    print(f"\nDONE   {total} recorded runs are now {total} spans in project "
          f"'fleet-week'\n       — real timestamps, real durations, tokens, "
          f"cost and outcome as attributes.")
    print("\nNOTE   nothing was re-run and nothing was invented: a ledger "
          "you already had\n       is one exporter away from any OTel "
          "backend. Records first.")
    print("\nopen   http://localhost:6006 · project 'fleet-week'")


if __name__ == "__main__":
    main()
