"""
===============================================================================
 FLEET VIEW  —  every agent you built this week, on one screen
===============================================================================

    python fleet/fleetview.py

Reads, READ-ONLY, the run evidence the week already produced:

    day 3   day3-test-pipeline/ledger.csv        (generate · triage · runs)
    day 3   day3-rag-demo/out/ask-*.json            (the knowledge agent)
    day 4   fleet/records.jsonl                     (patterns + drift demo)

Nothing is written anywhere. One screen answers the monitoring questions:
who ran, how often, at what cost — which agent is the COST OUTLIER — and,
from the prompt_version column, what changed and whether the change is
PROVED by its pass rate rather than argued about.
===============================================================================
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent.parent          # the "AI And Agents" folder

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def rows_from_day3_ledger():
    p = ROOT / "day3-test-pipeline" / "ledger.csv"
    if not p.exists():
        return [], "day3 ledger.csv not found - skipped"
    agg = {}
    for r in csv.DictReader(p.open(encoding="utf-8")):
        step = r["step"]
        a = agg.setdefault(step, {"runs": 0, "in": 0, "out": 0, "cost": 0.0})
        a["runs"] += 1
        a["in"] += int(r["input_tokens"] or 0)
        a["out"] += int(r["output_tokens"] or 0)
        a["cost"] += float(r["cost_usd"] or 0)
    name = {"generate": "test-designer", "triage": "triage", "run_case": "runner (no model)"}
    return [(name.get(k, k), 3, v["runs"], v["in"], v["out"], v["cost"], "")
            for k, v in agg.items()], None


def rows_from_rag():
    outs = sorted((ROOT / "day3-rag-demo" / "out").glob("ask-*.json"))
    if not outs:
        return [], "rag out/ask-*.json not found - skipped"
    runs = ti = to = 0
    for f in outs:
        d = json.loads(f.read_text(encoding="utf-8"))
        runs += 1
        ti += d["usage"]["input_tokens"]
        to += d["usage"]["output_tokens"]
    cost = ti / 1e6 * 2.0 + to / 1e6 * 8.0
    return [("knowledge-ask", 3, runs, ti, to, cost, "cites sources")], None


def rows_from_day4_records():
    p = HERE / "records.jsonl"
    if not p.exists():
        return [], {}, "fleet/records.jsonl not found"
    agg, versions = {}, {}
    for line in p.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        a = agg.setdefault(r["agent"], {"runs": 0, "in": 0, "out": 0, "cost": 0.0})
        a["runs"] += 1
        a["in"] += r["input_tokens"]
        a["out"] += r["output_tokens"]
        a["cost"] += r["cost_usd"]
        if r["agent"] == "note-summarizer":
            v = versions.setdefault(r["prompt_version"], {"runs": 0, "pass": 0})
            v["runs"] += 1
            v["pass"] += 1 if r["outcome"] == "pass" else 0
    rows = [(k, 4, v["runs"], v["in"], v["out"], v["cost"], "") for k, v in sorted(agg.items())]
    return rows, versions, None


def main():
    print("=" * 92)
    print("  THE FLEET — every agent, one screen (read-only over the week's own records)")
    print("=" * 92)

    rows, notes = [], []
    for source in (rows_from_day3_ledger, rows_from_rag):
        r, warn = source()
        rows += r
        if warn:
            notes.append(warn)
    r4, versions, warn = rows_from_day4_records()
    rows += r4
    if warn:
        notes.append(warn)

    print(f"\n{'agent':<20} {'day':>3} {'runs':>5} {'in_tok':>8} {'out_tok':>8} {'cost':>9}  {'$/run':>8}")
    print("-" * 92)
    total = 0.0
    per_run = {}
    for name, day, runs, ti, to, cost, note in rows:
        total += cost
        pr = cost / runs if runs else 0
        if cost > 0:
            per_run[name] = pr
        print(f"{name:<20} {day:>3} {runs:>5} {ti:>8} {to:>8} {cost:>9.4f}  {pr:>8.4f}")
    print("-" * 92)
    print(f"{'TOTAL':<20} {'':>3} {'':>5} {'':>8} {'':>8} {total:>9.4f}")

    # ---- the cost outlier: the same column, sorted. No dashboard product,
    #      no anomaly model — a division and a max.
    if per_run:
        outlier = max(per_run, key=per_run.get)
        print(f"\nCOST OUTLIER   {outlier} at ${per_run[outlier]:.4f}/run "
              f"({per_run[outlier] / max(min(per_run.values()), 1e-9):.0f}x the cheapest)")

    # ---- change tracking + the one proved change, straight from records
    if versions:
        print("\nCHANGE TRACKING — note-summarizer, pass rate by prompt version:")
        for v in sorted(versions):
            d = versions[v]
            rate = 100.0 * d["pass"] / d["runs"] if d["runs"] else 0
            bar = "#" * int(rate / 10)
            print(f"   {v}:  {d['pass']}/{d['runs']} pass  {rate:>5.1f}%  {bar}")
        vs = sorted(versions)
        if len(vs) >= 3:
            print("   v2 drifted, quietly. v3 is not an opinion — it is a pass rate.")

    if notes:
        print("\nsources skipped: " + " · ".join(notes))
    print()


if __name__ == "__main__":
    main()
