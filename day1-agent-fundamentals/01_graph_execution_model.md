# Phase 1.1 – The Graph Execution Model Under the Hood

This is the first lesson in the advanced LangGraph track. It includes a **short primer** (Part 1) for anyone who has only skimmed the LangGraph docs. From Part 2 onward we go under the hood — SuperSteps, the Pregel-inspired execution engine, execution boundaries, and the sync-vs-async trade-off — with hands-on labs against Azure OpenAI.

---

## Prerequisites

- You have completed `environment_setup.md`.
- `.venv-langgraph` is activated.
- `python hello_graph.py` runs successfully.
- You know basic Python typing (`TypedDict`, `Annotated`) and async (`async def`, `await`).

If `hello_graph.py` fails, fix that before continuing — every exercise here depends on Azure OpenAI working end-to-end.

---

## Learning Objectives

### Core

- Build a LangGraph `StateGraph` from scratch (primer)
- Explain what a **SuperStep** is and why LangGraph uses them
- Draw the execution boundary around a SuperStep and predict when state updates become visible
- Describe LangGraph's Pregel-inspired engine in one paragraph, without hand-waving
- Write **synchronous** and **asynchronous** nodes in the same graph

### Advanced

- Predict the execution order when multiple nodes are scheduled in the same SuperStep
- Choose between `graph.invoke`, `graph.stream`, and `graph.astream` for production workloads
- Benchmark sync-node latency vs async-node throughput under concurrent load
- Diagnose "my node ran twice!" and "my state update was lost" from stream output

---

## Part 1: Primer — A LangGraph in 60 Lines

Skip this part if you can already:
- Define a `StateGraph` with typed state
- Add nodes and edges
- Compile and invoke the graph
- Explain why `START` and `END` exist

Otherwise, work through it. Everything after Part 2 assumes this vocabulary.

### The Mental Model

LangGraph is a library for running **stateful, multi-step workflows** where each step can call an LLM, a tool, or a deterministic function. A LangGraph application has three parts:

| Piece | What it is |
|-------|-----------|
| **State** | A typed dictionary (or Pydantic model) that flows through the graph. Each node reads from it and returns updates. |
| **Nodes** | Python functions that take the current state and return a **partial** state dict with fields to update. |
| **Edges** | Directed connections describing which node runs next. Can be static (`add_edge`) or conditional (`add_conditional_edges`). |

### Your First Graph

Create `phase1/01_graph_execution_model/01_primer.py`:

```python
"""Primer: a 3-node graph that plans, answers, and formats."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import env_loader  # noqa: F401

import os
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langchain_openai import AzureChatOpenAI


class State(TypedDict):
    question: str
    plan: str
    raw_answer: str
    final_answer: str


llm = AzureChatOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    temperature=0,
)


def plan_node(state: State) -> dict:
    q = state["question"]
    reply = llm.invoke(
        f"List 2-3 bullet points you would need to answer: {q}. "
        "Just the bullets, no prose."
    )
    return {"plan": reply.content}


def answer_node(state: State) -> dict:
    reply = llm.invoke(
        f"Question: {state['question']}\n\n"
        f"Outline:\n{state['plan']}\n\n"
        "Write a 3-sentence answer."
    )
    return {"raw_answer": reply.content}


def format_node(state: State) -> dict:
    return {"final_answer": f"ANSWER:\n{state['raw_answer'].strip()}"}


builder = StateGraph(State)
builder.add_node("plan", plan_node)
builder.add_node("answer", answer_node)
builder.add_node("format", format_node)

builder.add_edge(START, "plan")
builder.add_edge("plan", "answer")
builder.add_edge("answer", "format")
builder.add_edge("format", END)

graph = builder.compile()


if __name__ == "__main__":
    result = graph.invoke({"question": "Why does LangGraph model execution as a graph?"})
    print(result["final_answer"])
```

Run it:

```bash
cd ~/langgraph-labs
python phase1/01_graph_execution_model/01_primer.py
```

You should see a three-sentence answer printed under `ANSWER:`.

### What Just Happened

1. `StateGraph(State)` created a builder that validates node returns against `State`.
2. `add_node` registered each function under a name.
3. `add_edge(START, "plan")` said "start here".
4. `compile()` converted the builder into an executable graph.
5. `graph.invoke({...})` ran the graph; each node's return dict was merged into the running state.
6. When execution reached `END`, the final state was returned.

### Two Things the Primer Hid From You

**(a) Nodes don't return the full state — they return partial updates.** `plan_node` returns only `{"plan": ...}`. LangGraph merges that into the running state dict. This matters later when two parallel nodes return updates for the same key (Lesson 1.2's reducers).

**(b) The graph did not execute left-to-right line by line.** Internally, LangGraph ran a loop: schedule nodes whose inputs are ready → execute them → apply their output to state → repeat. That loop is what we study next.

---

## Part 2: SuperSteps — The Unit of Execution

A **SuperStep** is LangGraph's atomic execution boundary. One SuperStep = "one iteration of the engine's scheduling loop". Inside a SuperStep:

1. **Plan phase** — the engine looks at the current state, figures out which nodes are ready to run (i.e., nodes whose incoming edges have fired this tick), and schedules them.
2. **Execute phase** — all scheduled nodes for this SuperStep run concurrently (more on "concurrently" below).
3. **Commit phase** — each node's returned partial state is merged into a single new state snapshot. **Only after all scheduled nodes finish is the new state visible.**

That last bullet is the critical one. Writes a node makes during a SuperStep are **not** visible to other nodes running in the same SuperStep — they become visible in the *next* SuperStep.

### Why Does That Matter?

Consider two nodes scheduled in the same SuperStep. Node A writes `{"flag": True}`. Node B reads `state["flag"]`. In the same SuperStep, B sees the **old** value of `flag` — whatever it was when the SuperStep started. B only sees A's update on the next SuperStep.

This is not a bug. It's the same semantics Google's Pregel paper described for graph processing, and it's what makes LangGraph safe to parallelize.

### Visualizing a SuperStep

```
SuperStep N:
  ┌─ State snapshot (read-only to all nodes this step) ─┐
  │                                                     │
  │  Node A ──►  partial update Δ_A                     │
  │  Node B ──►  partial update Δ_B                     │
  │                                                     │
  └─────────────────────────────────────────────────────┘
                           │
                           ▼
                  Commit: merge Δ_A, Δ_B into state
                           │
                           ▼
SuperStep N+1: schedule next nodes using NEW state
```

### Observing SuperSteps with `graph.stream`

`graph.invoke` hides the SuperStep loop. `graph.stream` exposes each SuperStep's output so you can see the engine's pulses.

Create `phase1/01_graph_execution_model/02_superstep_stream.py`:

```python
"""Shows each SuperStep as it commits."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import env_loader  # noqa: F401

import os
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langchain_openai import AzureChatOpenAI


class State(TypedDict):
    question: str
    plan: str
    answer: str


llm = AzureChatOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    temperature=0,
)


def plan(state: State) -> dict:
    r = llm.invoke(f"Outline 2 bullets for: {state['question']}. Bullets only.")
    return {"plan": r.content}


def answer(state: State) -> dict:
    r = llm.invoke(f"Given outline:\n{state['plan']}\nAnswer: {state['question']}")
    return {"answer": r.content}


builder = StateGraph(State)
builder.add_node("plan", plan)
builder.add_node("answer", answer)
builder.add_edge(START, "plan")
builder.add_edge("plan", "answer")
builder.add_edge("answer", END)
graph = builder.compile()


if __name__ == "__main__":
    for step, update in enumerate(graph.stream(
        {"question": "What is a SuperStep?"},
        stream_mode="updates",
    )):
        print(f"\n=== SuperStep {step} ===")
        for node_name, partial_state in update.items():
            print(f"Node that ran: {node_name}")
            for k, v in partial_state.items():
                preview = str(v)[:120].replace("\n", " ")
                print(f"  {k} = {preview}...")
```

Run it:

```bash
python phase1/01_graph_execution_model/02_superstep_stream.py
```

Output (trimmed):

```
=== SuperStep 0 ===
Node that ran: plan
  plan = - Define LangGraph's execution unit - Explain why parallelism is safe...

=== SuperStep 1 ===
Node that ran: answer
  answer = A SuperStep is one iteration of the scheduling loop...
```

Two SuperSteps, one node per SuperStep — because the graph is linear.

### `stream_mode` Options

| Mode | What You See Each Tick |
|------|------------------------|
| `updates` | Only the partial state returned by the node(s) that just ran |
| `values` | The full state after each SuperStep commits |
| `debug` | Detailed trace including task scheduling events |
| `messages` | Token-by-token message stream (for chat-style graphs) |

Try re-running with `stream_mode="values"` and `stream_mode="debug"` to compare. `debug` is the closest you get to peeking at the scheduler's internal planning.

---

## Part 3: The Pregel Influence

LangGraph's engine is explicitly modeled on **Pregel**, the graph-processing framework Google described in 2010 ([Malewicz et al., SIGMOD 2010](https://dl.acm.org/doi/10.1145/1807167.1807184)). Don't worry about reading the paper — the borrowed ideas are simple:

| Pregel concept | LangGraph concept |
|----------------|-------------------|
| Vertex | Node |
| Message | Partial state update |
| Superstep | SuperStep |
| Combiner | Reducer (Lesson 1.2) |
| Aggregator | Global channel |
| Halt | Node returns no edges / `END` reached |

The key property LangGraph inherits from Pregel: **the engine is deterministic about when updates become visible, regardless of how nodes are parallelized**. Two nodes running "at the same time" cannot race because their writes both go into the same commit barrier at the end of the SuperStep.

### Why Not Just Use `asyncio.gather()`?

You could write a workflow with bare `asyncio.gather()` calls and merge results manually. What LangGraph buys you over raw `asyncio`:

- **Deterministic visibility semantics** — writes become visible in the next SuperStep, always.
- **Checkpointing** — the state after each SuperStep is a natural save point (Phase 4).
- **Conditional routing** that is recomputed each SuperStep (Lesson 1.3).
- **Interrupts and resume** at SuperStep boundaries (Phase 2).
- **Tracing** with SuperStep-aligned spans (Phase 6).

If you don't need any of those, `asyncio` is indeed simpler. LangGraph earns its complexity on non-trivial workflows.

---

## Part 4: Execution Boundaries

An **execution boundary** is a point where the engine can safely pause, persist state, or hand control back to the caller. In LangGraph, every SuperStep boundary is an execution boundary.

That's why all of these features "just work" at SuperStep boundaries:

1. **Checkpointing** — the checkpointer writes state between SuperSteps (Phase 4).
2. **Interrupts** — `interrupt_before` and `interrupt_after` fire at SuperStep boundaries (Phase 2).
3. **Streaming** — each SuperStep produces one `stream` event.
4. **Cancellation** — if the caller cancels, the engine finishes the current SuperStep atomically and stops.

Within a SuperStep, there is no execution boundary. If you try to interrupt mid-node, you will get partial work that can't cleanly resume.

### Demo: SuperStep Boundary = Checkpoint Boundary

Create `phase1/01_graph_execution_model/03_boundaries.py`:

```python
"""Shows that state is fully committed only at SuperStep boundaries."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import env_loader  # noqa: F401

from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver


class State(TypedDict):
    step: int
    trail: list


def a(state: State) -> dict:
    print(f"  [node a] reading step={state['step']}")
    return {"step": state["step"] + 1, "trail": state["trail"] + ["a"]}


def b(state: State) -> dict:
    print(f"  [node b] reading step={state['step']}")
    return {"step": state["step"] + 10, "trail": state["trail"] + ["b"]}


builder = StateGraph(State)
builder.add_node("a", a)
builder.add_node("b", b)
builder.add_edge(START, "a")
builder.add_edge("a", "b")
builder.add_edge("b", END)

graph = builder.compile(checkpointer=MemorySaver())

if __name__ == "__main__":
    config = {"configurable": {"thread_id": "demo"}}
    result = graph.invoke({"step": 0, "trail": []}, config=config)
    print("final state:", result)

    print("\nCheckpoint history:")
    for cp in graph.get_state_history(config):
        print(f"  step={cp.values['step']:>3}  trail={cp.values['trail']}  next={cp.next}")
```

Run it:

```bash
python phase1/01_graph_execution_model/03_boundaries.py
```

Notice how `get_state_history` returns one entry per SuperStep — not one per node, not one per line of code.

> **Note:** `trail` uses `list` concatenation because this lesson uses the **default replace semantics** — node `b` will replace node `a`'s trail contribution unless we read-then-append, which is what `state["trail"] + ["b"]` does. Lesson 1.2 shows how custom reducers remove the need for this pattern.

---

## Part 5: Synchronous vs. Asynchronous Nodes

LangGraph accepts both sync and async node functions in the same graph. But your choice changes how the engine executes them inside a SuperStep.

### Rule of Thumb

| Node Type | When to Use It | SuperStep Behavior |
|-----------|----------------|--------------------|
| `def node(state)` (sync) | CPU-bound transforms, Pydantic validation, small data wrangling | Ran on a thread-pool executor; blocks one worker thread |
| `async def node(state)` (async) | Any I/O: LLM calls, HTTP, DB, vector stores | Ran on the event loop; multiple can progress on one core |

Because LLM calls are network I/O, **the vast majority of real-world LangGraph nodes should be async**. Sync nodes are fine, but they waste a thread while the LLM call is in flight.

### Demo: Parallel Async Nodes Finish Faster

Create `phase1/01_graph_execution_model/04_sync_vs_async.py`:

```python
"""Compare sync vs async nodes when running 3 LLM calls concurrently."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import env_loader  # noqa: F401

import asyncio
import os
import time
from typing import TypedDict
from operator import add
from typing import Annotated

from langgraph.graph import StateGraph, START, END
from langchain_openai import AzureChatOpenAI


class State(TypedDict):
    topic: str
    summaries: Annotated[list, add]  # Lesson 1.2 previews the `add` reducer


llm = AzureChatOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    temperature=0,
)


# ---- Sync variant ----
def sync_sub(aspect: str):
    def _node(state: State) -> dict:
        r = llm.invoke(f"In one sentence, describe {aspect} of {state['topic']}.")
        return {"summaries": [r.content]}
    return _node


# ---- Async variant ----
def async_sub(aspect: str):
    async def _node(state: State) -> dict:
        r = await llm.ainvoke(f"In one sentence, describe {aspect} of {state['topic']}.")
        return {"summaries": [r.content]}
    return _node


def build(factory):
    b = StateGraph(State)
    for name in ["history", "technology", "economics"]:
        b.add_node(name, factory(name))
        b.add_edge(START, name)
        b.add_edge(name, END)
    return b.compile()


def run_sync():
    g = build(sync_sub)
    t0 = time.perf_counter()
    out = g.invoke({"topic": "coffee", "summaries": []})
    print(f"sync : {time.perf_counter() - t0:5.2f}s  {len(out['summaries'])} summaries")


async def run_async():
    g = build(async_sub)
    t0 = time.perf_counter()
    out = await g.ainvoke({"topic": "coffee", "summaries": []})
    print(f"async: {time.perf_counter() - t0:5.2f}s  {len(out['summaries'])} summaries")


if __name__ == "__main__":
    run_sync()
    asyncio.run(run_async())
```

Run it:

```bash
python phase1/01_graph_execution_model/04_sync_vs_async.py
```

Typical output:

```
sync :  3.41s  3 summaries
async:  1.18s  3 summaries
```

The sync version runs the three nodes in parallel on threads, but each thread still blocks on I/O. The async version interleaves the three LLM calls on a single event loop and wins by ~3x.

> **Subtle point:** Even sync nodes run in parallel inside a SuperStep — LangGraph uses a thread-pool executor. So "sync" does not mean "serial". It means "blocks a thread".

### When Sync Is Actually Fine

- Node does only in-memory work (Pydantic model construction, list merging, regex).
- Node calls a very fast library (`numpy`, `pandas`).
- Node's runtime is dominated by CPU, not I/O — threads don't help here either, but async adds zero benefit.

### Mixed Graphs

You can mix sync and async nodes freely. `graph.invoke` will transparently call sync nodes in the thread pool; `graph.ainvoke` will `await` async nodes on the event loop. No decoration needed — the engine inspects the function.

---

## Part 6: `invoke` vs `stream` vs `astream`

| API | When to Use | Returns |
|-----|-------------|---------|
| `graph.invoke(input)` | Sync callers, you only care about the final state | Dict |
| `graph.ainvoke(input)` | Async callers, you only care about the final state | Awaitable → Dict |
| `graph.stream(input, stream_mode=...)` | Sync callers, you want per-SuperStep progress | Iterator |
| `graph.astream(input, stream_mode=...)` | Async callers (FastAPI, Azure Functions), you want progress or token-level streaming | Async iterator |

**Rule of thumb for production:** serve graphs from async web frameworks using `astream`, not `invoke`. You can still collect the final state by exhausting the stream, but streaming lets you send partial progress to the client.

Create `phase1/01_graph_execution_model/05_astream.py`:

```python
"""Async streaming — what a FastAPI handler would do."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import env_loader  # noqa: F401

import asyncio
import os
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langchain_openai import AzureChatOpenAI


class State(TypedDict):
    topic: str
    outline: str
    essay: str


llm = AzureChatOpenAI(
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    api_key=os.environ["AZURE_OPENAI_API_KEY"],
    api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    azure_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"],
    temperature=0,
)


async def outline(state: State) -> dict:
    r = await llm.ainvoke(f"Outline a 3-paragraph essay on: {state['topic']}. Bullets only.")
    return {"outline": r.content}


async def essay(state: State) -> dict:
    r = await llm.ainvoke(
        f"Write a 3-paragraph essay on '{state['topic']}' using this outline:\n{state['outline']}"
    )
    return {"essay": r.content}


b = StateGraph(State)
b.add_node("outline", outline)
b.add_node("essay", essay)
b.add_edge(START, "outline")
b.add_edge("outline", "essay")
b.add_edge("essay", END)
graph = b.compile()


async def main():
    async for step, update in aenumerate(graph.astream(
        {"topic": "the invention of the bicycle"}, stream_mode="updates"
    )):
        node = list(update.keys())[0]
        print(f"[step {step}] {node} finished")


async def aenumerate(it):
    i = 0
    async for x in it:
        yield i, x
        i += 1


if __name__ == "__main__":
    asyncio.run(main())
```

Run it:

```bash
python phase1/01_graph_execution_model/05_astream.py
```

---

## Exercises

### Exercise 1 — Predict the SuperStep Count

Given this graph:

```python
builder = StateGraph(State)
builder.add_node("a", a)
builder.add_node("b", b)
builder.add_node("c", c)
builder.add_node("d", d)
builder.add_edge(START, "a")
builder.add_edge(START, "b")   # fan out
builder.add_edge("a", "c")
builder.add_edge("b", "c")     # fan in
builder.add_edge("c", "d")
builder.add_edge("d", END)
```

**Question:** How many SuperSteps does this graph use to complete, assuming all nodes succeed? Sketch it before reading the answer.

**Answer:** 3.

- **SuperStep 0:** `a` and `b` both run (both have edges from `START`).
- **SuperStep 1:** `c` runs (both incoming edges fired in SuperStep 0).
- **SuperStep 2:** `d` runs.

Verify it yourself by writing trivial sync nodes that print their name, streaming with `stream_mode="updates"`, and counting yields.

### Exercise 2 — Make an LLM Graph Async

Open `01_primer.py`. Convert all three nodes to `async def` using `llm.ainvoke` and call the graph with `graph.ainvoke(...)` inside `asyncio.run(...)`. Time both versions (`time python ...`). Is the async version faster on a linear graph? Why or why not?

**Expected finding:** Roughly the same speed. Async helps only when multiple I/O-bound nodes run **in the same SuperStep**. A linear graph has one node per SuperStep, so there's nothing to overlap.

### Exercise 3 — Fan-Out Timing

Build a graph with one `entry` node and **five** parallel LLM-calling nodes that all run in the same SuperStep. Compare total wall time between the sync and async versions.

**Hint:** Use `Annotated[list, add]` for the aggregated-results field so the five nodes can all append to it. (Previewing Lesson 1.2's reducers.)

**Expected finding:** Async is ~5x faster here, because all five LLM calls now overlap on one event loop instead of blocking five threads.

### Exercise 4 — `stream_mode="debug"` Scavenger Hunt

Re-run `02_superstep_stream.py` with `stream_mode="debug"`. Scan the output for:

- A `"task"` event with a `step` field
- A `"task_result"` event
- The `writes` payload showing what the node contributed to state

You'll use these tags again in Phase 6 when we wire up LangSmith tracing.

---

## Optional Advanced Exercises

> **Scenario:** You're the platform engineer owning the "ask-the-knowledge-base" service. The product team is complaining that p95 latency spiked when they added a second LLM step to the workflow. You need to understand *why* before you can fix it.

### Part 7 (Optional) — Measuring Where the Time Goes

Add timing spans around each node without using LangSmith yet.

```python
import time
from contextlib import contextmanager

@contextmanager
def span(name):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt = (time.perf_counter() - t0) * 1000
        print(f"[span] {name} {dt:7.1f} ms")


async def outline(state):
    with span("outline.llm"):
        r = await llm.ainvoke(...)
    return {"outline": r.content}
```

Run a 10-question benchmark and check whether your SuperStep count equals your span count. If not, you have a hidden second node or a retry firing — both worth investigating.

### Part 8 (Optional) — Kill a Node Mid-Flight

What happens if a node raises an exception inside a SuperStep? Try it:

```python
def flaky(state):
    raise RuntimeError("simulated outage")
```

Add this node and run the graph. Observe:

- The exception bubbles out of `graph.invoke`.
- If you're using a checkpointer, state **before** this SuperStep is persisted — nothing committed after the crash.
- Retrying with the same `thread_id` resumes from the last committed SuperStep (proper coverage in Phase 4).

This is the boundary guarantee in action. Without SuperSteps, you'd have to hand-roll idempotency per node.

### Part 9 (Optional) — Parallel Fan-Out at Scale

Build a graph that fans out to 20 parallel summarizer nodes. Measure:

1. Sync version total wall time.
2. Async version total wall time.
3. Azure OpenAI **rate limit headers** in your trace.

You will hit a rate limit before 20 parallel calls finish. This is a real production concern: LangGraph happily parallelizes faster than Azure OpenAI will serve you. Lesson 3.2 revisits this with the `Send` API and explicit concurrency limits.

---

## Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| Node B reads stale value A just wrote | Both scheduled in same SuperStep | Insert an edge `A → B` so B runs in the next SuperStep |
| `asyncio.run` complains about a running loop | You're calling `graph.invoke` (sync) from inside an already-running event loop | Use `graph.ainvoke` instead |
| `graph.stream` never yields | Graph has an entry node but the state doesn't contain required keys | Provide all non-reducer state keys in the initial input |
| Node raises `TypeError: unhashable type: 'dict'` | You used a mutable default for a TypedDict field | Always pass initial values explicitly when invoking |
| `RecursionError` | Conditional edge creates an infinite loop | Add a `recursion_limit` to `graph.invoke(..., config={"recursion_limit": 25})` |

---

## Key Takeaways

- **A SuperStep is one tick of the engine's scheduling loop.** Plan → execute → commit. Repeat until `END`.
- **Writes commit at SuperStep boundaries.** Nodes in the same SuperStep see the state from the *start* of that step, not each other's in-flight updates.
- **LangGraph's engine is Pregel-inspired.** Deterministic visibility is the feature, not a quirk.
- **Execution boundaries = SuperStep boundaries.** Checkpoints, interrupts, and streaming events all align to them.
- **Async nodes are the default for I/O-bound work.** Sync nodes are fine for CPU-bound transforms but waste a thread per in-flight LLM call.
- **`stream` and `astream` are for production.** `invoke` is fine for scripts and tests.

---

## Quick Reference

| Task | Snippet |
|------|---------|
| Compile graph | `graph = builder.compile()` |
| Sync invoke | `graph.invoke(initial_state)` |
| Async invoke | `await graph.ainvoke(initial_state)` |
| Stream per-step updates | `for u in graph.stream(s, stream_mode="updates"): ...` |
| Stream full snapshots | `for v in graph.stream(s, stream_mode="values"): ...` |
| Debug stream | `for d in graph.stream(s, stream_mode="debug"): ...` |
| Limit SuperSteps | `graph.invoke(s, config={"recursion_limit": 50})` |
| Async stream | `async for u in graph.astream(s): ...` |
| Build fan-out/fan-in | `builder.add_edge(START, "a"); builder.add_edge(START, "b"); builder.add_edge("a", "c"); builder.add_edge("b", "c")` |
| Get state history | `graph.get_state_history(config)` (requires checkpointer) |

---

## What's Next

Lesson 1.2 takes everything you just learned about SuperStep commits and asks: *what happens when two parallel nodes write to the same key?* That's where **reducers** come in — and where `TypedDict` stops being enough.

---

## Cleanup

No cleanup required — this lesson only used Azure OpenAI API calls, no local state created.
