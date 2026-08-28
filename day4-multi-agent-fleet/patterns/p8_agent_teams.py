"""
===============================================================================
 P8  —  AGENT TEAMS: persistent workers pulling from a shared queue
===============================================================================

    python p8_agent_teams.py

USE CASE — a backlog sweep. Four rough story one-liners need refining into
real stories. Nobody assigns them: three workers PULL from a shared queue,
and whoever finishes first pulls again. Pace decides the split.

THE LANGGRAPH — build_worker() compiles a two-node StateGraph (assess ->
refine), and ALL THREE workers run that same compiled graph — a compiled
graph is stateless between invokes, so sharing it is safe. The queue and
the threads are deliberately OUTSIDE the graph: they are infrastructure.
That is this family's honest lesson — decoupled patterns wrap graphs in
infrastructure; not everything is coordination-by-graph.

No orchestrator exists anywhere in this file. The empty queue IS the
completion signal.
===============================================================================
"""
import json
import os
import queue
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import TypedDict

from dotenv import load_dotenv

# Load the Azure OpenAI credentials from this fixture's own .env file.
ROOT = Path(__file__).parent.parent
load_dotenv(ROOT / ".env")
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from langchain_openai import AzureChatOpenAI                 # noqa: E402
from langchain.agents import create_agent                    # noqa: E402
from langgraph.graph import StateGraph, START, END           # noqa: E402

# One client for the small fast model. Both agents in this file share it.
MODEL = os.environ.get("AZURE_OPENAI_DEPLOYMENT_FAST", "gpt-5.4-nano")
model = AzureChatOpenAI(azure_deployment=MODEL,
                        api_version=os.environ.get("OPENAI_API_VERSION",
                                                   "2025-04-01-preview"))

# The backlog — four rough one-liners waiting in the queue.
BACKLOG = [
    ("story-1", "users want to export their invoices"),
    ("story-2", "admin needs to bulk-deactivate users"),
    ("story-3", "customers keep asking for dark mode"),
    ("story-4", "let people download the audit log"),
]


# ---------------------------------------------------------------------------
# THE WORKER'S GRAPH — a two-node chain: assess, then refine.
# ---------------------------------------------------------------------------
class Item(TypedDict):
    raw: str
    kind: str
    story: str


assessor = create_agent(
    model=model, tools=[],
    system_prompt=("Classify the backlog one-liner: kind (feature/tech-debt/"
                   "compliance) + the ONE question to ask the requester. "
                   "2 short lines."))

refiner = create_agent(
    model=model, tools=[],
    system_prompt=("Rewrite the one-liner as a user story with 3 numbered, "
                   "testable acceptance criteria. Be terse."))


def assess(state: Item):
    # First node: classify the one-liner.
    result = assessor.invoke({"messages": [("user", state["raw"])]})
    count_tokens(result)
    return {"kind": str(result["messages"][-1].content)}


def refine(state: Item):
    # Second node: turn it into a real story, using the assessment.
    result = refiner.invoke({"messages": [
        ("user", f"{state['raw']}\nAssessment: {state['kind']}")]})
    count_tokens(result)
    return {"story": str(result["messages"][-1].content)}


def build_worker():
    b = StateGraph(Item)
    b.add_node("assess", assess)
    b.add_node("refine", refine)
    b.add_edge(START, "assess")
    b.add_edge("assess", "refine")
    b.add_edge("refine", END)
    return b.compile()


# ONE compiled graph, shared by all three workers. A compiled graph is
# stateless between invokes, so sharing it is safe.
worker_graph = build_worker()


# ---------------------------------------------------------------------------
# THE INFRASTRUCTURE — a queue, three threads, no boss. This part is
# deliberately OUTSIDE the graph: it is what "decoupled" means.
# ---------------------------------------------------------------------------
def worker(name, q, done):
    while True:
        # PULL the next story — nobody assigns work here.
        try:
            sid, raw = q.get_nowait()
        except queue.Empty:
            return                    # empty queue = this worker is done
        with LOCK:
            print(f"   [{name}] claimed {sid}")
        started = time.time()
        # Run the shared compiled graph on the claimed story.
        worker_graph.invoke({"raw": raw, "kind": "", "story": ""})
        with LOCK:
            print(f"   [{name}] done    {sid} in {time.time() - started:.1f}s")
            done.append((name, sid))


def main():
    print("P8 · agent teams — three workers, one queue, no orchestrator\n")

    # Fill the queue with the backlog.
    q = queue.Queue()
    for item in BACKLOG:
        q.put(item)
    done = []

    # Start three workers and wait for the queue to run dry.
    started = time.time()
    threads = [threading.Thread(target=worker, args=(f"w{i}", q, done))
               for i in (1, 2, 3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seconds = round(time.time() - started, 1)

    # Who did how many? Pace decided — not a boss.
    counts = {}
    for name, _ in done:
        counts[name] = counts.get(name, 0) + 1
    split = " · ".join(f"{w} did {n}" for w, n in sorted(counts.items()))
    print(f"\nCOMPLETE  {len(done)}/{len(BACKLOG)} — the empty queue IS the "
          f"completion signal · {split}")
    print("\nNOTE      each claim ran the SAME compiled two-node graph. The "
          "queue and threads\n          are infrastructure AROUND the graph "
          "— that is what 'decoupled' means.")
    record("p8-backlogteam", "agent-teams", USAGE, seconds,
           note=f"3 workers, {len(BACKLOG)} items")
    print(f"recorded · {USAGE['input_tokens']} in / "
          f"{USAGE['output_tokens']} out · {seconds}s")


# ---------------------------------------------------------------------------
# Bookkeeping — nothing below is part of the pattern.
# ---------------------------------------------------------------------------
USAGE = {"input_tokens": 0, "output_tokens": 0}
LOCK = threading.Lock()


def count_tokens(result):
    """Add this call's token usage to the running total for the run record.
    Three worker threads call this at once — hence the lock."""
    with LOCK:
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
