---
service: platform
doc_type: standard
version: 1.4
---
# Testing standards

## Boundary rule
Test the boundary the specification names, not a round number near it. If a
limit is 45 minutes, the interesting probes are 44, 45 and 46 minutes.

## Isolation rule
A test must pass alone and in any order. A test that depends on another test's
leftovers is a defect in the suite, whoever wrote it.

## Evidence rule
A failing test must report expected, observed, and the clause it protects —
enough for triage to act without re-running anything.
