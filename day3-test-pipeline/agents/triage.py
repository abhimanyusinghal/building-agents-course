"""
===============================================================================
 AGENT 3  —  TRIAGE
===============================================================================

WHAT IT DOES
    Takes a red run and turns each failure into a decision: what kind of problem
    this is, who owns it, and what should happen next.

WHY THIS IS AGENT WORK
    A failing test tells you something disagreed. It does not tell you WHO WAS
    WRONG - and that is the whole question.

        expected 400, got 409

    Is the API broken, or is the test out of date? The status codes cannot
    answer that. Only the contract can, and reading a document against an
    observation is judgement.

    This is the job that quietly eats a QA team: a red board on Monday morning
    and four hours of somebody senior working out which three of the eleven
    failures actually matter.

THE FOUR ANSWERS IT CAN GIVE
    contract_break  the API does not do what the contract says. Fix the API.
    stale_test      the test asserts something the contract no longer says.
                    Fix the test. The API is behaving correctly.
    environment     nothing is wrong with the code; the run was unlucky.
                    Infrastructure, a flaky dependency, a bad moment.
    real_defect     the API is broken in a way the contract did not anticipate.

    The third one is where triage goes to die. "Environment" is the comfortable
    answer: it blames nobody, closes the ticket, and costs nothing to say. It
    is also the answer a model will reach for when a failure LOOKS transient -
    and looking transient is not the same as being transient.

WHAT TO READ IN ITS OUTPUT
    Not the verdict. The EVIDENCE.

    Every verdict carries the observations it was built from. A confident
    classification standing on an empty evidence list is the tell, and
    --audit holds every verdict to yesterday's rule: only a failure PROVEN
    transient has earned a retry.

USAGE
    python -m agents.triage             # classify the failures in out/results.json
    python -m agents.triage --audit     # then hold each verdict to its own evidence
===============================================================================
"""
import argparse
import json
import re
import os
import time
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent.parent
load_dotenv(HERE / ".env")

from pydantic import BaseModel, Field                       # noqa: E402
from langchain_openai import AzureChatOpenAI                # noqa: E402
from langchain.agents import create_agent                   # noqa: E402
from langchain_core.tools import tool                       # noqa: E402

import ledger                                               # noqa: E402

CONTRACT_PATH = HERE / "contract/openapi.json"
OUT = HERE / "out"
MAX_TRIAGE_STEPS = 10

CLASSES = ("contract_break", "stale_test", "environment", "real_defect")


class Verdict(BaseModel):
    case_name: str = Field(description="Exactly the failing case's name.")
    classification: str = Field(
        description="One of: contract_break, stale_test, environment, real_defect")
    confidence: str = Field(description="high, medium, or low")
    evidence: list[str] = Field(
        description="The concrete observations from THIS run that support the "
                    "classification. Quote the contract clause or the observed "
                    "response. Do not write general reasoning here - only things "
                    "you actually saw.")
    duplicate_of: str = Field(
        default="",
        description="If another failure in this run has the same root cause, name it. Else empty.")
    owner: str = Field(description="Who fixes it: api-team, qa, or platform.")
    action: str = Field(description="One sentence. What should happen next.")


class Triage(BaseModel):
    verdicts: list[Verdict]
    summary: str = Field(description="One sentence a team lead could act on.")


@tool
def read_contract() -> str:
    """Read the API contract, to check whether a test's expectation is still correct."""
    return CONTRACT_PATH.read_text(encoding="utf-8")


SYSTEM_PROMPT = """You triage failing API tests.

For every failure you are given, decide which of these it is:

  contract_break  the API's behaviour contradicts the contract. The API is wrong.
  stale_test      the test's expectation contradicts the contract. The test is wrong.
  environment     nothing is wrong with the code - the run hit infrastructure trouble.
  real_defect     the API is broken in a way the contract does not cover.

Always call read_contract before deciding. The contract is the only thing that
can tell you whether the test or the API is the one out of step.

Rules for the evidence field:
- Put only what you actually observed: the expected value, the observed value,
  and the contract clause you checked. Quote them.
- If two failures share a root cause, use duplicate_of rather than repeating
  the analysis."""



def build():
    return create_agent(
        model=AzureChatOpenAI(
            azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
            api_version=os.environ.get("OPENAI_API_VERSION", "2025-04-01-preview"),
        ),
        tools=[read_contract],
        system_prompt=SYSTEM_PROMPT,
        response_format=Triage,
    )


def failures_from(results_path=None):
    path = Path(results_path) if results_path else OUT / "results.json"
    if not path.exists():
        print("No results to triage. Run the suite first:  python runner.py")
        raise SystemExit(1)
    data = json.loads(path.read_text(encoding="utf-8"))
    return [r for r in data["results"] if r["outcome"] != "pass"], data


def triage(failures):
    agent = build()
    payload = [{
        "name": f["name"],
        "request": {"method": f["method"], "path": f["path"],
                    "headers": f.get("headers") or {},
                    "repeat": f.get("repeat", 1)},
        "expected_status": f["expect_status"],
        "expected_headers": f.get("expect_headers") or [],
        "observed_status": f["actual_status"],
        "observed_headers": f.get("actual_headers") or {},
        "observed_body": f.get("actual_body"),
        "runner_reason": f["reason"],
        "case_came_from": f.get("source", "unknown"),
        "case_traces_to": f.get("traces_to", ""),
    } for f in failures]

    started = time.time()
    result = agent.invoke(
        {"messages": [{"role": "user", "content":
            "Triage these failing cases. One verdict each.\n\n"
            + json.dumps(payload, indent=2)}]},
        config={"recursion_limit": MAX_TRIAGE_STEPS * 2})

    usage = {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0}
    for m in result["messages"]:
        meta = getattr(m, "usage_metadata", None)
        if meta:
            usage["input_tokens"] += meta.get("input_tokens", 0)
            usage["output_tokens"] += meta.get("output_tokens", 0)
        usage["tool_calls"] += len(getattr(m, "tool_calls", []) or [])

    out = result["structured_response"]
    ledger.record("failures", "triage", time.time() - started, usage,
                  note=f"{len(out.verdicts)} verdicts")
    return out, usage, round(time.time() - started, 1)


# =============================================================================
#  THE AUDIT  -  Day 2's rule, applied to this agent's own output
# =============================================================================
#
# Yesterday: "transient failures retry, and only idempotent steps ever earn a
# retry". The half nobody applies is the FIRST half - a failure has to be proven
# transient before retrying it is a legitimate response.
#
# So: find every verdict that assumes transience, and ask what it actually saw.

# Words that describe a SYMPTOM. Seeing one proves nothing: a permanent hang and
# a busy afternoon look identical from outside.
SYMPTOM_WORDS = ("timeout", "timed out", "readtimeout", "connection reset",
                 "unavailable", "503", "504", "no response")

# Words that describe VARIATION ACROSS ATTEMPTS. Only these are evidence of
# transience, because transience is a claim about what happens when you try
# again - and you cannot make that claim from a single attempt.
PROOF_WORDS = ("retry succeeded", "succeeded on retry", "passed on retry",
               "second attempt succeeded", "passed on rerun", "intermittent",
               "not reproducible", "only sometimes", "flaky", "succeeded when repeated")

# Actions that assume transience.
#
# The negative lookahead earns its keep: "Retry-After" is the name of an HTTP
# header, and a verdict that says "add the Retry-After header" is not proposing
# a retry - it is proposing a code change. Matching it as one flagged three
# perfectly sound verdicts and buried the single verdict that mattered.
RETRY_RX = re.compile(r"(retry|rerun|re-run|run again|try again)(?!-after)",
                      re.IGNORECASE)


def audit(verdicts):
    """Every verdict that claims transience without having observed any."""
    flags = []
    for v in verdicts:
        claims_transient = (v.classification == "environment"
                            or bool(RETRY_RX.search(v.action)))
        if not claims_transient:
            continue
        blob = " ".join(v.evidence).lower()
        if any(w in blob for w in PROOF_WORDS):
            continue                    # it did observe variation. fair enough.
        symptoms = sorted({w for w in SYMPTOM_WORDS if w in blob})
        flags.append((v, symptoms))
    return flags


def main():
    ap = argparse.ArgumentParser(description="Turn a red run into decisions.")
    ap.add_argument("--audit", action="store_true",
                    help="hold every verdict to the evidence it offered")
    ap.add_argument("--results", default=None)
    args = ap.parse_args()

    failures, run = failures_from(args.results)
    if not failures:
        print(f"{run['passed']} passed, nothing failed. Nothing to triage.")
        return

    print(f"triaging {len(failures)} failures from a run of {run['total']}")
    print()
    out, usage, seconds = triage(failures)

    order = {"contract_break": 0, "real_defect": 1, "stale_test": 2, "environment": 3}
    for v in sorted(out.verdicts, key=lambda x: order.get(x.classification, 9)):
        print(f"  {v.classification.upper():<15} {v.confidence:<7} {v.owner:<10} {v.case_name[:44]}")
        for e in v.evidence:
            print(f"        - {e[:104]}")
        if v.duplicate_of:
            print(f"        same root cause as: {v.duplicate_of[:60]}")
        print(f"        -> {v.action[:104]}")
        print()

    counts = {}
    for v in out.verdicts:
        counts[v.classification] = counts.get(v.classification, 0) + 1
    print("  " + " | ".join(f"{n} {k}" for k, n in sorted(counts.items())))
    print(f"  {usage['tool_calls']} tool calls, {usage['input_tokens']} in / "
          f"{usage['output_tokens']} out, ${ledger.cost_of(usage):.4f}, {seconds}s")
    print()
    print(f"  summary: {out.summary}")

    OUT.mkdir(exist_ok=True)
    (OUT / "triage.json").write_text(json.dumps(
        {"seconds": seconds, "usage": usage, "summary": out.summary,
         "verdicts": [v.model_dump() for v in out.verdicts]}, indent=2), encoding="utf-8")
    print()
    print("written to out/triage.json")

    if args.audit:
        bar = "=" * 74
        print()
        print(bar)
        print("  AUDIT - every verdict that assumes transience, held to its evidence")
        print(bar)
        print("  Day 2's rule: a transient failure may be retried - but it has to be")
        print("  PROVEN transient first. One attempt cannot prove it.")
        print()
        flagged = audit(out.verdicts)
        if not flagged:
            print("  Nothing flagged. Every retry recommendation rests on an observed retry.")
        for v, symptoms in flagged:
            print(f"  {v.case_name}")
            print(f"    verdict : {v.classification}, confidence {v.confidence}")
            print(f"    action  : \"{v.action}\"")
            print(f"    evidence it offered:")
            for e in v.evidence:
                print(f"        - {e[:96]}")
            print()
            if symptoms:
                print(f"    What it saw: {', '.join(symptoms)} - a SYMPTOM.")
                print(f"    A permanent hang and a busy afternoon look identical from outside.")
            print(f"    What is missing: any second attempt. Nothing here was tried twice,")
            print(f"    so nothing here shows the outcome would ever be different.")
            print(f"    It recommends a rerun on the strength of how the failure is SHAPED.")
            print()
        if flagged:
            print(f"  {len(flagged)} verdict(s) told you not to trust them - in their own output.")
            print(f"  The verdict was confident. The evidence was one observation.")
            print(f"  Read the evidence, not the verdict.")


if __name__ == "__main__":
    main()
