# otel/ — the fleet on the industry pipe (OpenTelemetry)

C4 of Day 4. Extends the fleet story: C3 computed the fleet view from our
own JSONL with a division and a max; this module shows the same evidence on
the industry-standard pipe — OpenTelemetry — in two backends. **No pattern
file is touched.** The eleven demos never learn they are being watched.

## One-time setup

    pip install arize-phoenix arize-phoenix-otel openinference-instrumentation-langchain
    docker pull grafana/otel-lgtm          # only for the --both beat

Verified with: arize-phoenix 20.4.0, openinference-instrumentation-langchain 0.1.73,
langchain 1.3.17 / langgraph 1.2.11, Python 3.13, Docker 29.

## Start the backends (pre-flight, before the session)

    python -m phoenix.server.main serve                    # UI on :6006, OTLP gRPC on :4317
    docker run -d --name lgtm -p 3010:3000 -p 4318:4318 grafana/otel-lgtm
        # Grafana on :3010 and OTLP HTTP on :4318. Phoenix already owns
        # OTLP gRPC on :4317, so the two backends get one OTLP port each.
        # If a port is taken on your machine, remap the host side (-p).

## The three beats

| beat | command | what appears |
|---|---|---|
| trace a live run | `python otel/otel_run.py patterns/p7_magentic.py` | one trace, ~29 spans: manager turns, specialists, the routing functions, every LLM call with `llm.token_count.*` — at http://localhost:6006, project `p7_magentic` |
| replay the week | `python otel/backfill_ledger.py` | one span per recorded run (fleet/records.jsonl + day 3's ledger.csv, read-only), real timestamps and durations, cost/outcome as attributes — project `fleet-week` |
| second backend | `python otel/otel_run.py patterns/p4_handoff.py --both` | the SAME run lands in Phoenix *and* Grafana (http://localhost:3010 → Drilldown/Explore → Traces) — one extra exporter, zero code change |

## The teaching lines

- **Instrumentation is orthogonal to code.** `otel_run.py` registers a
  tracer provider and hooks the LangChain callback layer, then runs the
  unmodified demo file. The graph you drew is the trace you see — the
  inner `create_agent` graphs appear nested inside the outer graph's
  spans, and even the routing functions show up as spans.
- **The trace agrees with the ledger.** P1 traced: 536 LLM tokens across
  3 calls; its ledger line: 308 in + 228 out = 536. Two independent
  witnesses, same number.
- **Records first.** The backfill proves the order of operations: a ledger
  you already had is one exporter away from any OTLP backend. Phoenix
  today; Grafana, Datadog or Azure Monitor tomorrow — config, not rewrite.
- The traced runs STILL write their `fleet/records.jsonl` line. OTel
  complements the ledger; it does not replace it.

## Cleanup

    docker rm -f lgtm            # stop Grafana stack
    # Phoenix: Ctrl+C its terminal. Data persists in ~/.phoenix (delete to reset).
