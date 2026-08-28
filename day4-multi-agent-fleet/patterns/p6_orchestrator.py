"""
===============================================================================
 P6  —  ORCHESTRATOR-SUBAGENT: branches decided at RUN time (langgraph Send)
===============================================================================

    python p6_orchestrator.py

USE CASE — an incoming feature spec. A lead agent reads it, decides WHICH
specialist checks this particular spec needs (security? api design? test
plan? privacy?), writes a one-line instruction for each, and synthesizes
their reports into one verdict. Different spec, different fan-out.

THE LANGGRAPH — compare P2: there the three branches were DRAWN at build
time. Here the branches do not exist until the lead answers — the routing
function returns a list of Send(...) objects, one per task the lead chose,
and LangGraph creates those branches on the fly, in parallel. That is the
whole difference between concurrent and orchestrated.

Anthropic's coordination guidance calls this the default multi-agent
pattern: a lead that plans, subagents that execute, one synthesis.
===============================================================================
"""
import json
import operator
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Annotated, Literal, TypedDict

from dotenv import load_dotenv

# Load the Azure OpenAI credentials from this fixture's own .env file.
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from pydantic import BaseModel, Field                        # noqa: E402
from langchain_openai import AzureChatOpenAI                 # noqa: E402
from langchain.agents import create_agent                    # noqa: E402
from langgraph.graph import StateGraph, START, END           # noqa: E402
from langgraph.types import Send                             # noqa: E402

# One client for the small fast model. Every agent in this file shares it.
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")
model = AzureChatOpenAI(azure_deployment=MODEL,
                        api_version=os.environ.get("OPENAI_API_VERSION",
                                                   "2025-04-01-preview"))

# The feature spec the lead will read and plan reviews for.
SPEC = ("Add passwordless magic-link login to the portal: POST "
        "/auth/magic-link sends a 15-minute single-use sign-in link to the "
        "account e-mail; works alongside password login; rolled out behind "
        "a feature flag.")


# The lead answers in a fixed shape: a plan — one task per chosen specialist.
class Task(BaseModel):
    specialist: Literal["security", "api-design", "test-plan", "privacy"]
    instruction: str = Field(description="one line, specific to this spec")


class Plan(BaseModel):
    tasks: list[Task]


# ---------------------------------------------------------------------------
# THE STATE. The reports field has a REDUCER (operator.add): the parallel
# branches all append to it, and LangGraph merges the writes.
# ---------------------------------------------------------------------------
class Flow(TypedDict):
    spec: str
    tasks: list
    reports: Annotated[list, operator.add]
    summary: str


# ---------------------------------------------------------------------------
# THE AGENTS — a deciding lead, four specialists, and a closer.
# ---------------------------------------------------------------------------
lead = create_agent(
    model=model, tools=[],
    system_prompt=("You are the review lead. Read the feature spec and "
                   "decide which specialists from the roster this spec "
                   "needs — only the ones that earn their keep — with one "
                   "specific instruction each. Roster: security, "
                   "api-design, test-plan, privacy."),
    response_format=Plan)

security_specialist = create_agent(
    model=model, tools=[],
    system_prompt=("Security specialist. Answer the instruction about the "
                   "spec in max 3 one-line findings."))

api_design_specialist = create_agent(
    model=model, tools=[],
    system_prompt=("API design specialist. Answer the instruction about "
                   "the spec in max 3 one-line findings."))

test_plan_specialist = create_agent(
    model=model, tools=[],
    system_prompt=("Test specialist. Answer the instruction about the spec "
                   "in max 3 one-line test cases."))

privacy_specialist = create_agent(
    model=model, tools=[],
    system_prompt=("Privacy specialist. Answer the instruction about the "
                   "spec in max 3 one-line findings."))

# The Send payload names the specialist; this dict picks the right agent.
SPECIALIST_AGENTS = {"security": security_specialist,
                     "api-design": api_design_specialist,
                     "test-plan": test_plan_specialist,
                     "privacy": privacy_specialist}

closer = create_agent(
    model=model, tools=[],
    system_prompt=("Synthesize the specialist reports into: verdict line "
                   "(ready to build / needs work) + the two most important "
                   "findings. 3 lines total."))


# ---------------------------------------------------------------------------
# THE NODES.
# ---------------------------------------------------------------------------
def plan(state: Flow):
    # The lead reads THIS spec and decides which specialists it needs.
    result = lead.invoke({"messages": [("user", state["spec"])]})
    count_tokens(result)
    p: Plan = result["structured_response"]
    print(f"PLAN   the lead chose {len(p.tasks)} specialists for THIS spec:")
    for t in p.tasks:
        print(f"   {t.specialist:<11} <- {t.instruction[:64]}")
    return {"tasks": [t.model_dump() for t in p.tasks]}


# ---------------------------------------------------------------------------
# THE PATTERN IS THIS FUNCTION: one Send per task in the plan. The branches
# are created HERE, at run time — they did not exist when the graph was
# drawn. Each Send carries its own private payload to the specialist node.
# ---------------------------------------------------------------------------
def fan_out(state: Flow):
    return [Send("specialist", {"who": t["specialist"],
                                "instruction": t["instruction"],
                                "spec": state["spec"]})
            for t in state["tasks"]]


def specialist(payload):
    # ONE generic node; the Send payload tells it who to be. Runs once per
    # task, in parallel. The payload is this branch's own private state, so
    # token counts also travel through the report entry (parallel branches
    # must not share a counter).
    who = payload["who"]
    agent_for_task = SPECIALIST_AGENTS[who]
    result = agent_for_task.invoke({"messages": [
        ("user", f"Spec: {payload['spec']}\nInstruction: "
                 f"{payload['instruction']}")]})
    tokens_in = tokens_out = 0
    for m in result["messages"]:
        u = getattr(m, "usage_metadata", None)
        if u:
            tokens_in += u.get("input_tokens", 0)
            tokens_out += u.get("output_tokens", 0)
    text = str(result["messages"][-1].content)
    first = next((l.strip() for l in text.splitlines() if l.strip()), "")
    print(f"   REPORT {who:<11} {first[:62]}")
    return {"reports": [{"who": who, "text": text,
                         "input_tokens": tokens_in,
                         "output_tokens": tokens_out}]}


def synthesize(state: Flow):
    # The join ran: ALL reports are in. One agent writes the verdict.
    ask = "\n\n".join(f"[{r['who']}]\n{r['text']}" for r in state["reports"])
    result = closer.invoke({"messages": [("user", ask)]})
    count_tokens(result)
    return {"summary": str(result["messages"][-1].content)}


def build_graph():
    b = StateGraph(Flow)
    b.add_node("plan", plan)
    b.add_node("specialist", specialist)
    b.add_node("synthesize", synthesize)
    b.add_edge(START, "plan")
    b.add_conditional_edges("plan", fan_out, ["specialist"])  # Send fan-out
    b.add_edge("specialist", "synthesize")     # join: waits for ALL branches
    b.add_edge("synthesize", END)
    return b.compile()


def main():
    print("P6 · orchestrator-subagent — the lead decides the branches at "
          "run time\n")
    print(f"SPEC   {SPEC[:82]}...\n")

    # One invoke: plan, fan out, synthesize.
    started = time.time()
    final = build_graph().invoke({"spec": SPEC, "tasks": [], "reports": [],
                                  "summary": ""})
    seconds = round(time.time() - started, 1)

    print("\nSYNTHESIS")
    for line in final["summary"].splitlines()[:3]:
        if line.strip():
            print(f"   {line.strip()[:84]}")

    # Fold the branch token counts (carried in the reports) into the total.
    for r in final["reports"]:
        USAGE["input_tokens"] += r["input_tokens"]
        USAGE["output_tokens"] += r["output_tokens"]
    print("\nNOTE   P2's branches were drawn before the run; these were "
          "decided DURING it.\n       Weakness on the slide: the lead is a "
          "bottleneck and a single point of judgement.")
    record("p6-reviewlead", "orchestrator", USAGE, seconds,
           note=f"{len(final['tasks'])} Send branches")
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
    """One JSON line per run to fleet/records.jsonl — same shape as
    fleet/record.py, inlined so this demo stays one self-contained file."""
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
