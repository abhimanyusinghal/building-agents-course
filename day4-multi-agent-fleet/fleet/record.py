"""
===============================================================================
 RECORD  —  one JSON line per run, for every agent, always
===============================================================================

The rule of day 4: an agent run that leaves no record did not happen.

Each record answers the questions you will ask three weeks later:
which agent, doing what, under which prompt version, on which model,
at what cost, and did its output pass its own checks.

fleet/records.jsonl is what the fleet view reads. Every pattern demo run
this afternoon lands here — so by the time the fleet view comes up, the
day's own history is already on it.
===============================================================================
"""
import json
import time
import uuid
from pathlib import Path

HERE = Path(__file__).parent
RECORDS = HERE / "records.jsonl"

# $ per 1M tokens (input, output). Adjust to your price sheet; the SHAPE of
# the record is the lesson, the constants are bookkeeping.
PRICES = {
    "gpt-5.4": (2.00, 8.00),
    "gpt-5.4-nano": (0.05, 0.40),
}


def cost_of(model, usage):
    pin, pout = PRICES.get(model, (0.0, 0.0))
    return usage.get("input_tokens", 0) / 1e6 * pin + usage.get("output_tokens", 0) / 1e6 * pout


def record(agent, pattern, model, usage, seconds, outcome="ok", note="",
           prompt_version="v1"):
    """Append one run record. Never overwrites, never edits — a ledger."""
    rec = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "run_id": uuid.uuid4().hex[:8],
        "agent": agent,
        "pattern": pattern,
        "prompt_version": prompt_version,
        "model": model,
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
        "cost_usd": round(cost_of(model, usage), 6),
        "seconds": seconds,
        "outcome": outcome,
        "note": note,
    }
    with RECORDS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return rec
