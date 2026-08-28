"""
===============================================================================
 OTEL RUN  —  trace any pattern demo, WITHOUT touching its file
===============================================================================

    python otel/otel_run.py patterns/p7_magentic.py
    python otel/otel_run.py patterns/p4_handoff.py --both

The demo file runs UNCHANGED (runpy executes it as __main__). Everything
observability lives HERE, outside the demo:

  1. phoenix.otel.register() builds a standard OpenTelemetry tracer
     provider exporting OTLP to Phoenix (http://localhost:6006).
  2. auto_instrument=True switches on the OpenInference LangChain
     instrumentor — it hooks the callback layer that create_agent and
     LangGraph already emit, so every node, agent loop and LLM call
     becomes a span, with gen-ai token counts as attributes.

That is OpenTelemetry's core design point: instrumentation is orthogonal
to code. The demo does not know it is being watched — and it still writes
its fleet/records.jsonl line, because OTel complements the ledger, it does
not replace it.

--both adds a SECOND exporter to the SAME provider, pointed at the Grafana
otel-lgtm container (OTLP HTTP :4318). One run, two backends, zero code
change — the vendor is a config choice, not a rewrite.
===============================================================================
"""
import os
import runpy
import sys
from pathlib import Path

from phoenix.otel import register

GRAFANA_OTLP = "http://localhost:4318/v1/traces"


def main():
    args = [a for a in sys.argv[1:]]
    both = "--both" in args
    if both:
        args.remove("--both")
    if not args:
        print("usage: python otel/otel_run.py <demo.py> [--both]")
        sys.exit(1)
    target = Path(args[0]).resolve()
    project = target.stem                       # one Phoenix project per demo

    # -- 1. the OTel pipeline: provider + OTLP exporter to Phoenix ----------
    os.environ.setdefault("OTEL_SERVICE_NAME", f"day4-{project}")
    provider = register(project_name=project,
                        set_global_tracer_provider=True, verbose=False)

    # -- 1b. hook the LangChain/LangGraph callback layer. One line: every
    #        graph node, agent loop and LLM call becomes a span.
    from openinference.instrumentation.langchain import LangChainInstrumentor
    LangChainInstrumentor().instrument(tracer_provider=provider)

    # -- 2. optional second backend: same spans, second exporter ------------
    #    replace_default_processor=False KEEPS the Phoenix exporter — the
    #    same spans now fan out to two backends at once.
    if both:
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter)
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=GRAFANA_OTLP)),
            replace_default_processor=False)
        print(f"[otel] second exporter -> Grafana at {GRAFANA_OTLP}")

    print(f"[otel] tracing '{project}' -> http://localhost:6006  "
          f"(the demo file is untouched)\n")

    # -- 3. run the demo exactly as if it had been typed directly -----------
    sys.argv = [str(target)]
    runpy.run_path(str(target), run_name="__main__")

    provider.force_flush()
    print(f"\n[otel] spans flushed · open http://localhost:6006 · "
          f"project '{project}'")


if __name__ == "__main__":
    main()
