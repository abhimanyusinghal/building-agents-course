# day4-multi-agent-fleet — patterns, then governance

Eleven multi-agent coordination patterns, each a **single self-contained
file** — no shared module, no imports to chase. Each is a proper LangGraph
build (`StateGraph`, edges, conditional edges, `Send`, `Command`, reducers,
`recursion_limit`) with a use case chosen so the pattern is the obvious tool
for it. Then the governance half: an inventory, run records, drift detection,
a fleet view, and OpenTelemetry.

Setup: copy `.env.example` to `.env` and fill it in. The patterns run on the
fast deployment (`AZURE_OPENAI_DEPLOYMENT_FAST`); every run appends a record
to `fleet/records.jsonl` (a ten-line inline writer, same shape as
`fleet/record.py`) — so by the time you run the fleet view, your own runs are
already on it.

Verified on langgraph 1.2.11.

## The eleven pattern demos (patterns/)

| # | pattern | use case | the LangGraph idea | watch for |
|---|---|---|---|---|
| P0 | agent as tool | story refiner + DoR checker | `@tool` wraps a compiled graph | the inner agent inside the outer tool log |
| P1 | sequential | support-mail intake pipeline | four plain `add_edge` lines | output becoming input, three times |
| P2 | concurrent | one PR diff, three review lenses | 3 edges out of START + `operator.add` reducer | agent time > wall clock |
| P3 | generator-verifier | customer incident notice vs comms checklist | conditional edge closing a cycle | REJECTED + feedback -> ACCEPTED (cap 3) |
| P4 | handoff | ticket routed to the owning desk | node returns `Command(goto=...)` | no drawn edge out of front_desk |
| P5 | group chat | ship/no-ship with dev, qa, pm | moderator cycle + a written house rule | three voices argue from their OWN briefed facts |
| P6 | orchestrator-subagent | feature spec -> chosen specialist checks | `Send` fan-out decided at run time | branches created from the plan |
| P7 | magentic | open-ended bug investigation | supervisor cycle, ledger in state, written finish | the ledger grows; "a fix plan exists" ends the run |
| P8 | agent teams | backlog sweep, 3 workers | one compiled graph shared by threads | a worker claiming a second story |
| P9 | message bus | ops events, growing listeners | code bus connecting compiled graphs | EXTEND with one line; one event dies silently |
| P10 | shared state | incident hypothesis board | board = state field with reducer; cycle + written end | findings building on the board |

Run any of them from `patterns/`:

    python p7_magentic.py

Each file reads top to bottom: the state, the agents (every brief visible),
the nodes (written out in full), the wiring (marked `THE PATTERN`), and a
`Bookkeeping` section that is not part of the pattern.

Honest engineering, disclosed where it matters:

- **P3** — the drafter is not given the checklist; the verifier owns it.
  That split is realistic and is why round 1 fails. Accepts in round 2–3;
  occasionally the round cap ends it — both endings teach.
- **P5** — the speakers argue from role + knowledge + accountability, never
  scripted opinions. A written house rule guarantees every voice is heard
  before the PM's call, and closes the meeting once it is made.
- **P7** — the fix-planner refuses to plan until the ledger holds BOTH log
  and code evidence. Completion is machinery: "a fix plan exists" is a
  written rule in the routing function — leave it to the model and it
  re-polishes forever.

## The governance builds (fleet/)

    python fleet/inventory.py     # the register, linted: owner + identity + cap
    python fleet/drift_demo.py    # v1 pass -> v2 quietly wrong -> v3 proved
    python fleet/fleetview.py     # every agent, one screen, outlier + change tracking

The fleet view also reads, **read-only**, the Day 3 ledgers
(`../day3-test-pipeline/ledger.csv` and `../day3-rag-demo/out/`) — run those
days first and your whole course history appears on one screen.

Records accumulate on purpose — that is rather the point. Delete
`fleet/records.jsonl` any time for a clean slate (it recreates on the next
run). `fleet/records-dev.jsonl` is the archived history of *building* these
demos — 44 runs, $0.0315 — kept as its own teaching artifact.

## OpenTelemetry (otel/)

Trace any pattern demo without touching its file, replay the ledgers as
spans, and land the same run in Phoenix AND Grafana at once. Setup, commands
and ports: `otel/README.md`.
