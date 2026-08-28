"""
===============================================================================
 P9  —  MESSAGE BUS: agents that publish and subscribe, never meet
===============================================================================

    python p9_message_bus.py

USE CASE — ops events. Things happen (an auth error spikes, a deploy goes
out) and DIFFERENT parties care for different reasons. Publishers do not
know who listens; subscribers do not know who published. New listeners
join without touching anything that exists.

THE LANGGRAPH — each subscriber is an agent built with create_agent, and
create_agent returns a COMPILED LANGGRAPH GRAPH (the day-1 loop). The bus
itself — topics, matching, delivery — is thirty lines of code and stays
code ON PURPOSE: routing by topic name is a rule you can write down, and a
rule you can write down should never be sent to a model. The bus is the
part of the system LangGraph deliberately does not model; it CONNECTS
graphs, it is not one.

Watch the last event: it dies with no subscriber — silently. The delivery
log is why you would ever know.
===============================================================================
"""
import json
import os
import sys
import time
import uuid
from fnmatch import fnmatch
from pathlib import Path

from dotenv import load_dotenv

# Load the Azure OpenAI credentials from this fixture's own .env file.
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_openai import AzureChatOpenAI                 # noqa: E402
from langchain.agents import create_agent                    # noqa: E402

# One client for the small fast model. Every subscriber shares it.
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")
model = AzureChatOpenAI(azure_deployment=MODEL,
                        api_version=os.environ.get("OPENAI_API_VERSION",
                                                   "2025-04-01-preview"))


# ---------------------------------------------------------------------------
# THE SUBSCRIBER AGENTS. Each is built with create_agent — which returns a
# compiled LangGraph graph. The bus below carries events BETWEEN graphs.
# ---------------------------------------------------------------------------
auth_investigator = create_agent(
    model=model, tools=[],
    system_prompt=("You triage auth alerts: likely cause + first check, "
                   "one line."))

release_watcher = create_agent(
    model=model, tools=[],
    system_prompt=("You watch deploys: what to monitor for the next hour, "
                   "one line."))

compliance = create_agent(
    model=model, tools=[],
    system_prompt=("You keep the compliance file: say in one line under "
                   "which policy this alert must be filed."))


# ---------------------------------------------------------------------------
# THE BUS — topics, pattern matching, a delivery log. Thirty lines of CODE,
# on purpose: topic routing is a rule you can write down, and a rule you
# can write down is never sent to a model.
# ---------------------------------------------------------------------------
class Bus:
    def __init__(self):
        self.subs = []                       # (topic_pattern, name, agent)
        self.log = []                        # every delivery, always

    def subscribe(self, pattern, name, subscriber):
        # One line joins the system. Nothing that exists is touched.
        self.subs.append((pattern, name, subscriber))

    def publish(self, topic, event):
        print(f"\nPUBLISH {topic:<14} {event[:56]}")
        # Which subscribers match this topic? fnmatch handles wildcards
        # like "alert.*" — plain code, no model.
        hits = [(n, a) for p, n, a in self.subs if fnmatch(topic, p)]
        if not hits:
            # No subscriber: the event dies SILENTLY. Only the log knows.
            self.log.append((topic, "NO SUBSCRIBER"))
            print("        -> no subscriber — the event died SILENTLY. "
                  "The delivery log is\n           the only reason you "
                  "know it happened.")
            return
        # Deliver the event to every matching subscriber agent.
        for name, sub in hits:
            result = sub.invoke({"messages": [
                ("user", f"topic: {topic}\nevent: {event}")]})
            count_tokens(result)
            text = " ".join(str(result["messages"][-1].content).split())
            self.log.append((topic, name))
            print(f"        -> {name}: {text[:64]}")


def main():
    print("P9 · message bus — publishers and subscribers that never meet")
    started = time.time()

    # Wire the initial system: two subscribers, each on one topic.
    bus = Bus()
    bus.subscribe("alert.auth", "auth-investigator", auth_investigator)
    bus.subscribe("deploy", "release-watcher", release_watcher)

    # Events happen. The publishers do not know who is listening.
    bus.publish("alert.auth", "ERR_AUTH_1042 rate x40 in 10 min, EU region")
    bus.publish("deploy", "portal v2.4.1 to production (invoice-export fix)")

    # THE PAYOFF: extend the system with one line. A new subscriber joins
    # on a wildcard — no existing agent, publisher or wire is touched.
    print("\nEXTEND  compliance joins, subscribing to 'alert.*' — no "
          "existing agent,\n        publisher or wire was touched:")
    bus.subscribe("alert.*", "compliance", compliance)

    # The same alert again — it now reaches TWO subscribers.
    bus.publish("alert.auth", "ERR_AUTH_1042 rate x40 sustained, EU region")
    # And one event nobody listens to — the warning label of this pattern.
    bus.publish("billing.invoice", "invoice run finished: 8,114 documents")

    seconds = round(time.time() - started, 1)
    print(f"\nDELIVERY LOG  {len(bus.log)} entries — every delivery and "
          f"every silent death, auditable")
    record("p9-opsbus", "message-bus", USAGE, seconds,
           note=f"{len(bus.log)} deliveries")
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
