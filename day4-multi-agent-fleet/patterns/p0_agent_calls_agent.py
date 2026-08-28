"""
===============================================================================
 P0  —  THE PRIMITIVE: an agent used by another agent, as a tool
===============================================================================

    python p0_agent_calls_agent.py

USE CASE — a story refiner that must not trust its own judgement of "ready".
The team has a Definition-of-Ready. So the refiner gets ONE tool — and that
tool is another agent, the readiness checker, with the DoR in its brief.

WHY THIS IS THE PRIMITIVE — create_agent returns a compiled LangGraph graph
(the think/act loop from day 1). Wrapping that graph in @tool puts one whole
graph inside another graph's loop. Every pattern this afternoon is a bigger
arrangement of exactly this move.
===============================================================================
"""
import json
import os
import sys
import time
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Load the Azure OpenAI credentials from this fixture's own .env file.
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pydantic import BaseModel, Field                        # noqa: E402
from langchain_openai import AzureChatOpenAI                 # noqa: E402
from langchain.agents import create_agent                    # noqa: E402
from langchain_core.tools import tool                        # noqa: E402

# One client for the small fast model. Every agent in this file shares it —
# the pattern is the star today, not the prose.
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")
model = AzureChatOpenAI(azure_deployment=MODEL,
                        api_version=os.environ.get("OPENAI_API_VERSION",
                                                   "2025-04-01-preview"))

# The story we will refine — deliberately vague, so the checker has work.
STORY = ("As a portal user, I can reset my password so that I can regain "
         "access to my account.")


# ---------------------------------------------------------------------------
# THE INNER AGENT — the readiness checker. It owns the Definition of Ready,
# and it answers in a fixed shape: ready yes/no, plus what is missing.
# ---------------------------------------------------------------------------
class Readiness(BaseModel):
    ready: bool
    missing: list[str] = Field(description="what the story still lacks")


checker = create_agent(
    model=model,
    tools=[],
    system_prompt=("You check user stories against the team's Definition of "
                   "Ready: (1) numbered, testable acceptance criteria, "
                   "(2) error cases named, (3) out-of-scope stated. Report "
                   "ready true/false and what is missing."),
    response_format=Readiness)


# ---------------------------------------------------------------------------
# THE WRAP — one @tool decorator, and the whole checker agent becomes a tool.
# From the outside it looks like any other tool. Inside, a complete second
# agent runs its own loop.
# ---------------------------------------------------------------------------
@tool
def check_story(story: str) -> str:
    """Check a user story against the team's Definition of Ready."""
    # Run the inner agent, exactly like invoking any agent.
    result = checker.invoke({"messages": [("user", story)]})
    count_tokens(result)
    verdict: Readiness = result["structured_response"]
    # Narrate what just happened, so the room can see the nesting.
    print(f"   -> check_story(...)   [the inner agent runs its own loop here]")
    print(f"      inner agent says: ready={verdict.ready}, "
          f"missing={verdict.missing}")
    # The tool's return value is what the OUTER agent gets to read.
    return f"ready={verdict.ready}; missing={'; '.join(verdict.missing)}"


# ---------------------------------------------------------------------------
# THE OUTER AGENT — the refiner. Its one tool is the checker agent above.
# ---------------------------------------------------------------------------
refiner = create_agent(
    model=model,
    tools=[check_story],
    system_prompt=("Refine the user story you are given until it passes the "
                   "readiness check. Always call check_story first; then "
                   "rewrite the story fixing exactly what is missing. "
                   "Return only the final story text."))


def main():
    print("P0 · the primitive — an agent whose one tool is another agent\n")
    print(f"STORY        {STORY}\n")
    print("REFINER      starts. Watch its tool-call log:")

    # Run the outer agent. Somewhere inside its loop it will decide to call
    # check_story — and at that moment the inner agent runs.
    started = time.time()
    result = refiner.invoke({"messages": [("user", STORY)]})
    count_tokens(result)
    seconds = round(time.time() - started, 1)

    # Show the refined story (first lines are enough on a projector).
    final = result["messages"][-1].content
    print(f"\nRESULT       story rewritten with what the checker demanded:")
    for line in str(final).splitlines()[:6]:
        if line.strip():
            print(f"   {line.strip()[:86]}")

    print("\nNOTE         two agents, two briefs, one wire: the @tool decorator.")
    record("p0-refiner", "agent-as-tool", USAGE, seconds, note="inner: DoR checker")
    print(f"recorded · {USAGE['input_tokens']} in / "
          f"{USAGE['output_tokens']} out · {seconds}s")


# ---------------------------------------------------------------------------
# Bookkeeping — nothing below is part of the pattern.
# ---------------------------------------------------------------------------
USAGE = {"input_tokens": 0, "output_tokens": 0}


def count_tokens(result):
    """Add this call's token usage to the running total for the run record."""
    for m in result["messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            USAGE["input_tokens"] += u.get("input_tokens", 0)
            USAGE["output_tokens"] += u.get("output_tokens", 0)


def record(agent_name, pattern, usage, seconds, outcome="ok", note=""):
    """One JSON line per run to fleet/records.jsonl — a run without a record
    did not happen. Same shape as fleet/record.py; inlined so this demo is
    one self-contained file."""
    pin, pout = {"gpt-5.4": (2.00, 8.00)}.get(MODEL, (0.05, 0.40))
    rec = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
           "run_id": uuid.uuid4().hex[:8], "agent": agent_name,
           "pattern": pattern, "prompt_version": "v1", "model": MODEL,
           "input_tokens": usage["input_tokens"],
           "output_tokens": usage["output_tokens"],
           "cost_usd": round(usage["input_tokens"] / 1e6 * pin
                             + usage["output_tokens"] / 1e6 * pout, 6),
           "seconds": seconds, "outcome": outcome, "note": note}
    with (ROOT / "fleet" / "records.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


if __name__ == "__main__":
    main()
