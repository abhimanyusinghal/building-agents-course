"""
===============================================================================
 THE PIPELINE  —  the three of them, wired into one process
===============================================================================

Each of the three runs perfectly well on its own:

    python -m agents.generate      design the cases
    python runner.py               run them
    python -m agents.triage        decide what the failures mean

That is how you build them, and how you debug them. This file is what you ship:
the same three steps with the arrows drawn in, so one command takes you from a
contract to a set of decisions.

THE SHAPE IS YESTERDAY'S SHAPE
    A LangGraph state graph. Fixed steps, a folder that travels between them,
    one conditional edge. If you read graph.py on Day 2 you have read this
    already - which is the point. The spine does not change when the subject
    changes.

WHERE THE JUDGEMENT IS, AND WHERE IT IS NOT

    design_tests      AGENT      deciding what is worth testing
    run_suite         machinery  issuing requests, comparing values
    triage_failures   AGENT      deciding what a failure means
    audit_verdicts    machinery  holding a verdict to its own evidence

    Two agents, two pieces of machinery, alternating. The bill at the end shows
    the same alternation as a column of numbers: the machinery lines are zero.

THE CONDITIONAL EDGE
    If nothing failed there is nothing to triage, and the run ends early without
    calling the second agent. A green board should not cost anything.

USAGE
    python pipeline.py                    contract -> cases -> run -> decisions
    python pipeline.py --ungrounded       the same, with the contract taken away
    python pipeline.py --limit 8          a smaller suite
    python pipeline.py --bill             what the whole thing cost
===============================================================================
"""
import argparse
import json
import time
from pathlib import Path
from typing import Optional

from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

import ledger
import runner

HERE = Path(__file__).parent
OUT = HERE / "out"

CAPS = {
    "max_cases": 20,          # a suite bigger than this is padding, not coverage
    "max_run_seconds": 180,   # the whole pipeline, end to end
}


# =============================================================================
#  THE WORK ITEM  -  what travels between the four steps
# =============================================================================
class QARun(TypedDict):
    grounded: bool
    limit: int
    include_regression: bool
    cases: list
    results: Optional[dict]
    verdicts: list
    flagged: list


# =============================================================================
#  THE STEPS
# =============================================================================
def design_tests(run: QARun):
    """AGENT. Read the contract, decide what is worth testing."""
    from agents import generate
    started = time.time()
    suite, usage, _ = generate.generate(grounded=run["grounded"],
                                        limit=min(run["limit"], CAPS["max_cases"]))
    cases = [c.model_dump() for c in suite.cases]
    OUT.mkdir(exist_ok=True)
    (OUT / "cases.json").write_text(json.dumps(
        {"grounded": run["grounded"], "usage": usage, "reasoning": suite.reasoning,
         "cases": cases}, indent=2), encoding="utf-8")
    print(f"  {time.time() - started:5.1f}s  design_tests      "
          f"-> {len(cases)} cases, ${ledger.cost_of(usage):.4f}")
    return {"cases": cases}


def run_suite(run: QARun):
    """MACHINERY. Issue every request, check every answer. No model, no cost."""
    started = time.time()
    import requests
    try:
        requests.post(f"{runner.BASE}/_test/reset", timeout=5)
    except requests.RequestException:
        raise RuntimeError(f"The API is not answering on {runner.BASE}. "
                           f"Start it: python -m uvicorn api.app:app --port 8742")

    cases = runner.load_cases(include_regression=run["include_regression"])
    results = [runner.run_case(c) for c in cases]
    for r in results:
        ledger.record(r["name"], "run_case", r["seconds"], note=r["outcome"])

    passed = sum(1 for r in results if r["outcome"] == "pass")
    payload = {"base_url": runner.BASE, "total": len(results), "passed": passed,
               "failed": len(results) - passed,
               "seconds": round(time.time() - started, 2), "results": results}
    (OUT / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"  {time.time() - started:5.1f}s  run_suite         "
          f"-> {passed} passed, {len(results) - passed} failed, $0.0000")
    return {"results": payload}


def route_after_run(run: QARun) -> str:
    """Nothing failed? Then there is nothing to decide, and no reason to pay."""
    return "triage_failures" if run["results"]["failed"] else END


def triage_failures(run: QARun):
    """AGENT. Turn each failure into a decision."""
    from agents import triage as triage_mod
    started = time.time()
    failures = [r for r in run["results"]["results"] if r["outcome"] != "pass"]
    out, usage, _ = triage_mod.triage(failures)
    verdicts = [v.model_dump() for v in out.verdicts]
    (OUT / "triage.json").write_text(json.dumps(
        {"usage": usage, "summary": out.summary, "verdicts": verdicts},
        indent=2), encoding="utf-8")
    print(f"  {time.time() - started:5.1f}s  triage_failures   "
          f"-> {len(verdicts)} verdicts, ${ledger.cost_of(usage):.4f}")
    return {"verdicts": verdicts}


def audit_verdicts(run: QARun):
    """MACHINERY. Hold every verdict that assumes transience to its own evidence."""
    from agents import triage as triage_mod
    started = time.time()

    class _V:                                    # the audit reads attributes
        def __init__(self, d): self.__dict__.update(d)

    flagged = triage_mod.audit([_V(v) for v in run["verdicts"]])
    names = [v.case_name for v, _ in flagged]
    ledger.record("verdicts", "audit", time.time() - started, note=f"{len(names)} flagged")
    print(f"  {time.time() - started:5.1f}s  audit_verdicts    "
          f"-> {len(names)} verdict(s) not supported by their evidence, $0.0000")
    return {"flagged": names}


# =============================================================================
#  THE ARROWS
# =============================================================================
#
#   start -> design the cases      (agent)
#         -> run them              (machinery)
#         -> anything red?
#              no  -> stop. a green board costs nothing.
#              yes -> decide what each failure means   (agent)
#                  -> audit those decisions            (machinery)
#         -> done
#
def build_graph():
    b = StateGraph(QARun)
    b.add_node("design_tests", design_tests)
    b.add_node("run_suite", run_suite)
    b.add_node("triage_failures", triage_failures)
    b.add_node("audit_verdicts", audit_verdicts)

    b.add_edge(START, "design_tests")
    b.add_edge("design_tests", "run_suite")
    b.add_conditional_edges("run_suite", route_after_run,
                            {"triage_failures": "triage_failures", END: END})
    b.add_edge("triage_failures", "audit_verdicts")
    b.add_edge("audit_verdicts", END)
    return b.compile()


def main():
    ap = argparse.ArgumentParser(description="Contract in, decisions out.")
    ap.add_argument("--ungrounded", action="store_true", help="take the contract away")
    ap.add_argument("--limit", type=int, default=14)
    ap.add_argument("--no-regression", action="store_true")
    ap.add_argument("--bill", action="store_true", help="just print the ledger")
    args = ap.parse_args()

    if args.bill:
        ledger.bill()
        return

    print(f"contract -> cases -> run -> decisions"
          f"{'   (UNGROUNDED)' if args.ungrounded else ''}\n")
    started = time.time()
    final = build_graph().invoke({
        "grounded": not args.ungrounded, "limit": args.limit,
        "include_regression": not args.no_regression,
        "cases": [], "results": None, "verdicts": [], "flagged": [],
    })

    print(f"\n  {time.time() - started:.1f}s end to end\n")
    res = final["results"]
    if not res["failed"]:
        print(f"  {res['passed']} passed, nothing failed. Triage never ran.")
        return

    counts: dict[str, int] = {}
    for v in final["verdicts"]:
        counts[v["classification"]] = counts.get(v["classification"], 0) + 1
    print(f"  {res['passed']} passed, {res['failed']} failed")
    for k, n in sorted(counts.items()):
        print(f"    {n} {k}")
    if final["flagged"]:
        print(f"\n  {len(final['flagged'])} verdict(s) claim transience without having seen any:")
        for n in final["flagged"]:
            print(f"    - {n}")
        print("  Read the evidence, not the verdict.  (python -m agents.triage --audit)")
    print(f"\n  out/cases.json  out/results.json  out/triage.json")
    print(f"  what it cost:   python pipeline.py --bill")


if __name__ == "__main__":
    main()
