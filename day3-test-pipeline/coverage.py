"""
===============================================================================
 CLAUSE COVERAGE  —  which rules have no test, answered without reading tests
===============================================================================

The contract registers every rule with an id. Every case names the rule it
proves. So the question "what is not covered" is a set difference, and it takes
no judgement and no reading.

This matters because line coverage cannot answer it. You can have ninety per
cent of the lines and no case at all for the rule that says a readonly user
must not be able to write - because the code path that refuses them is one
branch, and nothing forces anybody to visit it.

    python coverage.py                # rules with no case
    python coverage.py --full         # every rule, and its case count
    python coverage.py --diff a.json b.json    # what moved between two suites
===============================================================================
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).parent
CONTRACT = json.loads((HERE / "contract/openapi.json").read_text(encoding="utf-8"))
RULES = {r["id"]: r for r in CONTRACT.get("x-rules", [])}


def load_suite(path):
    p = Path(path)
    if not p.is_absolute():
        p = HERE / p
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return d["cases"] if isinstance(d, dict) else d


def rules_in(cases):
    """rule id -> the cases that claim it."""
    hit = {}
    for c in cases:
        for rid in c.get("rule_ids") or ([c["traces_to"]] if c.get("traces_to") else []):
            rid = str(rid).strip()
            if rid in RULES:
                hit.setdefault(rid, []).append(c["name"])
    return hit


def report(cases, full=False):
    hit = rules_in(cases)
    missing = [rid for rid in RULES if rid not in hit]

    if full:
        print(f"{'rule':<14} {'cases':>5}  story        text")
        for rid, r in RULES.items():
            n = len(hit.get(rid, []))
            mark = "  " if n else "!!"
            print(f"{mark}{rid:<12} {n:>5}  {r['story']:<12} {r['text'][:64]}")
        print()

    print(f"{len(RULES) - len(missing)} of {len(RULES)} rules have at least one case.")
    if missing:
        print(f"\nNO CASE FOR:")
        for rid in missing:
            print(f"   {rid:<14} {RULES[rid]['story']:<12} {RULES[rid]['text']}")
        print(f"\n{len(missing)} rule(s) unproven. Line coverage cannot tell you this.")
    else:
        print("Every registered rule is claimed by at least one case.")
    return missing


def diff(a_path, b_path):
    """What moved between two generations. This is the review artefact."""
    a, b = load_suite(a_path), load_suite(b_path)
    if a is None or b is None:
        print("Both suites must exist.")
        raise SystemExit(1)
    an = {c["name"] for c in a}
    bn = {c["name"] for c in b}
    ha, hb = rules_in(a), rules_in(b)

    print(f"{Path(a_path).name}: {len(a)} cases, {len(ha)} rules covered")
    print(f"{Path(b_path).name}: {len(b)} cases, {len(hb)} rules covered\n")

    added, gone = sorted(bn - an), sorted(an - bn)
    for t, names in (("ADDED", added), ("DROPPED", gone)):
        if names:
            print(f"{t} ({len(names)})")
            for n in names:
                print(f"   {n[:88]}")
            print()

    rules_lost = sorted(set(ha) - set(hb))
    rules_won = sorted(set(hb) - set(ha))
    if rules_lost:
        print("RULES THAT LOST THEIR ONLY CASE:")
        for r in rules_lost:
            print(f"   {r:<14} {RULES[r]['text'][:70]}")
        print()
    if rules_won:
        print("RULES NEWLY COVERED:")
        for r in rules_won:
            print(f"   {r:<14} {RULES[r]['text'][:70]}")
        print()
    # The distinction that matters. Two suites can prove exactly the same rules
    # while sharing not one case name - and that is the normal outcome, because
    # naming is a free choice and the model makes it fresh every time.
    churn = len(set(added) | set(gone)) / max(len(an | bn), 1)
    same_rules = set(ha) == set(hb)
    print("-" * 66)
    print(f"rule coverage   {'IDENTICAL' if same_rules else 'CHANGED'}"
          f"   ({len(ha)} rules -> {len(hb)} rules)")
    print(f"case identity   {churn:.0%} churn   ({len(added)} added, {len(gone)} dropped)")
    print()
    if same_rules and churn > 0.5:
        print("Same rules proven. Almost no case survived by name.")
        print("Regenerate inside CI and every run has a different suite: failure history")
        print("does not join up, and per-case suppressions point at names that are gone.")
        print("Pin the suite. Regeneration is a change to review, not a build step.")
    else:
        print("Regeneration is a change. This diff is what gets reviewed - not the suite.")


def main():
    ap = argparse.ArgumentParser(description="Which contract rules have no test?")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--suite", default="suite.json")
    ap.add_argument("--diff", nargs=2, metavar=("OLD", "NEW"))
    args = ap.parse_args()

    if args.diff:
        diff(*args.diff)
        return

    cases = load_suite(args.suite)
    if cases is None:
        cases = load_suite("out/cases.json")
    if cases is None:
        print("No suite found. Generate one first:  python -m agents.generate")
        raise SystemExit(1)
    print(f"{len(cases)} cases against {len(RULES)} registered rules\n")
    missing = report(cases, full=args.full)
    raise SystemExit(1 if missing else 0)


if __name__ == "__main__":
    main()
