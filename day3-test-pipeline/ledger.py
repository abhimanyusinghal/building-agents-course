"""
===============================================================================
 THE LEDGER  —  the same idea as Day 2, pointed at a test suite
===============================================================================

One line per step, written as it happens: what ran, how long, what it consumed,
what it cost.

WHY IT MATTERS MORE HERE THAN IT DID YESTERDAY
    Yesterday it answered "what does one reviewed story cost?".

    Today it answers a sharper question. Three things happen in this pipeline -
    cases get written, cases get run, failures get triaged - and only two of
    them cost anything. When you read this file at the end of the session, the
    running is a column of zeros and the two agents are pennies.

    That is the argument for keeping the runner free of models, stated as
    arithmetic rather than as an opinion.
===============================================================================
"""
import csv
import os
import time
from pathlib import Path

LEDGER = Path(__file__).with_name("ledger.csv")
FIELDS = ["ts", "subject", "step", "seconds", "input_tokens", "output_tokens",
          "tool_calls", "cost_usd", "note"]


def _prices():
    return (float(os.environ.get("PRICE_IN_PER_1K", "0")),
            float(os.environ.get("PRICE_OUT_PER_1K", "0")))


def cost_of(usage):
    """What one step's tokens cost. Machinery has no tokens, so it costs zero."""
    usage = usage or {}
    p_in, p_out = _prices()
    return (usage.get("input_tokens", 0) / 1000) * p_in + \
           (usage.get("output_tokens", 0) / 1000) * p_out


def record(subject, step, seconds, usage=None, note=""):
    usage = usage or {}
    new = not LEDGER.exists()
    with LEDGER.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({
            "ts": time.strftime("%H:%M:%S"), "subject": str(subject)[:60], "step": step,
            "seconds": f"{seconds:.2f}",
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "tool_calls": usage.get("tool_calls", 0),
            "cost_usd": f"{cost_of(usage):.4f}", "note": note,
        })


def bill():
    """What the session cost, split by step. The shape is the point."""
    if not LEDGER.exists():
        print("No ledger yet.")
        return
    rows = list(csv.DictReader(LEDGER.open(encoding="utf-8")))
    steps = {}
    for r in rows:
        s = steps.setdefault(r["step"], {"n": 0, "sec": 0.0, "in": 0, "out": 0, "cost": 0.0})
        s["n"] += 1
        s["sec"] += float(r["seconds"])
        s["in"] += int(r["input_tokens"])
        s["out"] += int(r["output_tokens"])
        s["cost"] += float(r["cost_usd"])

    print(f"{'step':<14} {'runs':>5} {'seconds':>9} {'in_tok':>8} {'out_tok':>8} {'cost':>9}")
    for name, s in sorted(steps.items(), key=lambda kv: -kv[1]["cost"]):
        print(f"{name:<14} {s['n']:>5} {s['sec']:>9.1f} {s['in']:>8} {s['out']:>8} {s['cost']:>9.4f}")

    total = sum(s["cost"] for s in steps.values())
    machinery = sum(s["cost"] for n, s in steps.items() if n == "run_case")
    runs = steps.get("run_case", {"n": 0})["n"]
    print(f"\nTotal: ${total:.4f}")
    print(f"  of which {runs} test executions cost ${machinery:.4f} — "
          f"the machinery is free, and the ledger is where you prove it.")


if __name__ == "__main__":
    bill()
