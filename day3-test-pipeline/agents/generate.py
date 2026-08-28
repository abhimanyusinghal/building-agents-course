"""
===============================================================================
 AGENT 1  —  THE TEST DESIGNER
===============================================================================

WHAT IT DOES
    Reads the contract and decides which cases are worth writing.

WHY THIS IS AGENT WORK
    Deciding what to test is judgement. It is the same judgement a good tester
    makes reading a spec: where are the edges, what did the author forget to
    say, which rule is load-bearing and which is decoration.

    You cannot write that as an if-statement. Two competent testers hand the
    same contract will produce overlapping but different suites, and both will
    be defensible - which is the signature of judgement rather than machinery.

    What happens NEXT - issuing the request, comparing the status code - is not
    judgement at all, and it lives in runner.py with no model anywhere near it.

GROUNDING, AND WHY THE TOOL MATTERS
    The agent has exactly one tool: read the contract. Everything it writes has
    to come from that document, and every case has to name the clause it proves.

    Run it with --ungrounded and the tool is taken away. It still writes tests -
    fluent, plausible, and about an API it has imagined. That comparison is the
    point of the exercise: the difference between the two runs is not
    intelligence, it is grounding.

USAGE
    python -m agents.generate                # grounded on the contract
    python -m agents.generate --ungrounded   # the same agent, told nothing
    python -m agents.generate --limit 12     # fewer cases
===============================================================================
"""
import argparse
import json
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

MAX_DESIGN_STEPS = 10     # the cap: the planner gets a budget, not a blank cheque


# =============================================================================
#  THE CONTRACT  -  what a case must look like to be runnable
# =============================================================================
#
# Note what this shape forces. Every case must name the clause it proves
# (traces_to). A case that cannot say which sentence of the contract it is
# defending is not a test, it is a guess - and requiring the field is how you
# stop an agent quietly padding the suite.
#
class Fill(BaseModel):
    """How to build a long string without writing it out.

    A boundary case needs a note of exactly 4001 characters. Nobody wants that
    in a JSON file, and no agent should spend output tokens on it - so the case
    says which field, how long, and the runner makes the value.
    """
    field: str = Field(description="Which body field to fill, e.g. text")
    length: int = Field(description="How many characters")
    char: str = Field(default="x", description="Character to repeat")


class TestCase(BaseModel):
    name: str = Field(description="Short, specific, readable in a failure list.")
    method: str = Field(description="GET or POST.")
    path: str = Field(description="Concrete path with a real case id, e.g. /cases/CASE-1001/notes")
    path_template: str = Field(description="The contract's path, e.g. /cases/{case_id}/notes")
    headers: dict[str, str] = Field(default_factory=dict)
    body: dict | None = Field(default=None, description="JSON body, or null for GET.")
    fill: Fill | None = Field(
        default=None,
        description="For any string over 50 characters, use this instead of writing it out.")
    repeat: int = Field(default=1, description="Issue the request this many times; assert on the last. Use for rate limits.")
    expect_status: int = Field(description="The status the contract promises.")
    expect_headers: list[str] = Field(default_factory=list,
                                      description="Headers the contract requires on this response.")
    category: str = Field(description="happy, boundary, negative, or contract")
    rule_ids: list[str] = Field(
        description="The ids from the contract's x-rules register that this case proves, "
                    "e.g. [\"R-NOTE-LEN\"]. Use ids, not prose. A case proving nothing in "
                    "the register should not exist.")
    traces_to: str = Field(description="The clause, quoted, for a human reading the failure.")


class Suite(BaseModel):
    cases: list[TestCase]
    reasoning: str = Field(description="Two sentences: what you covered, and what you deliberately left out.")


# =============================================================================
#  THE TOOL  -  the only source of truth the agent is given
# =============================================================================
@tool
def read_contract() -> str:
    """Read the API contract: endpoints, request and response shapes, status codes, rules."""
    return CONTRACT_PATH.read_text(encoding="utf-8")


GROUNDED_PROMPT = """You design API test cases from a contract.

Call read_contract first. Everything you write must come from that document.

What makes a suite worth having:
- Test the BOUNDARY the contract names, not a round number near it. If a limit
  is 4000, the interesting values are 3999, 4000 and 4001. A case at 100 or at
  5000 proves nothing a reader did not already assume.
- Where the contract says a response MUST carry a header, assert the header.
  A status code alone will not catch a missing one.
- Test the rules a human argued about: state rules, permission rules, limits.
  Do not spend cases restating the happy path five ways.
- Every case names the rule ids it proves, from the x-rules register.
- Cover the register. A rule with no case is an untested promise.

Every request needs an X-Role header - agent, supervisor or readonly. Permissions
differ by role, and the register says which.

Use only the case ids the contract's x-fixtures section lists.
For any string longer than 50 characters use the fill field instead of writing it out.
Prefer a small sharp suite over a large shallow one."""

UNGROUNDED_PROMPT = """You design API test cases.

Write a test suite for a "Case Notes API" - an HTTP service where support agents
read cases and add notes to them, and can see a customer's recent orders.

Every case must name the rule it proves in traces_to."""


def build(grounded: bool):
    model = AzureChatOpenAI(
        azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
        api_version=os.environ.get("OPENAI_API_VERSION", "2025-04-01-preview"),
    )
    return create_agent(
        model=model,
        tools=[read_contract] if grounded else [],
        system_prompt=GROUNDED_PROMPT if grounded else UNGROUNDED_PROMPT,
        response_format=Suite,
    )


def generate(grounded=True, limit=14):
    agent = build(grounded)
    ask = (f"Design at most {limit} test cases for this API. "
           "Cover the boundaries and the rules that carry consequence.")
    started = time.time()
    result = agent.invoke({"messages": [{"role": "user", "content": ask}]},
                          config={"recursion_limit": MAX_DESIGN_STEPS * 2})

    usage = {"input_tokens": 0, "output_tokens": 0, "tool_calls": 0}
    for m in result["messages"]:
        meta = getattr(m, "usage_metadata", None)
        if meta:
            usage["input_tokens"] += meta.get("input_tokens", 0)
            usage["output_tokens"] += meta.get("output_tokens", 0)
        usage["tool_calls"] += len(getattr(m, "tool_calls", []) or [])

    suite = result["structured_response"]
    ledger.record("suite", "generate", time.time() - started, usage,
                  note=f"{len(suite.cases)} cases, {'grounded' if grounded else 'UNGROUNDED'}")
    return suite, usage, round(time.time() - started, 1)


def main():
    ap = argparse.ArgumentParser(description="Design test cases from the contract.")
    ap.add_argument("--ungrounded", action="store_true",
                    help="take the contract away and watch what happens")
    ap.add_argument("--limit", type=int, default=14)
    ap.add_argument("--out", default=None, help="output file (default out/cases.json)")
    args = ap.parse_args()

    grounded = not args.ungrounded
    print(f"designing cases — {'grounded on the contract' if grounded else 'NO CONTRACT'}\n")
    suite, usage, seconds = generate(grounded, args.limit)

    by_cat: dict[str, int] = {}
    for c in suite.cases:
        by_cat[c.category] = by_cat.get(c.category, 0) + 1

    for c in suite.cases:
        extra = f" x{c.repeat}" if c.repeat > 1 else ""
        fill = f"  [{c.fill.field}={c.fill.length} chars]" if c.fill else ""
        print(f"  {c.category:<9} {c.method:<5} {c.path:<34} -> {c.expect_status}{extra}{fill}")
        print(f"            {c.name}")
        print(f"            {','.join(c.rule_ids):<28} {c.traces_to[:56]}")

    OUT.mkdir(exist_ok=True)
    target = Path(args.out) if args.out else OUT / "cases.json"
    target.write_text(json.dumps(
        {"grounded": grounded, "seconds": seconds, "usage": usage,
         "reasoning": suite.reasoning,
         "cases": [c.model_dump() for c in suite.cases]}, indent=2), encoding="utf-8")

    print(f"\n{len(suite.cases)} cases — " + ", ".join(f"{n} {k}" for k, n in sorted(by_cat.items())))
    print(f"{usage['tool_calls']} tool calls, {usage['input_tokens']} in / "
          f"{usage['output_tokens']} out tokens, ${ledger.cost_of(usage):.4f}, {seconds}s")
    print(f"\nits own summary: {suite.reasoning}")
    print(f"\nwritten to {target.relative_to(HERE)}")


if __name__ == "__main__":
    main()
