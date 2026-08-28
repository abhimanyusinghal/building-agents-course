---
service: checkout
doc_type: adr
version: 1.0
---
# ADR-007 — Idempotency keys on payments

## Decision
Every payment-creating call carries a client-generated Idempotency-Key. Retries
with the same key return the first result. We accepted the storage cost because
double-charge incidents (see INC-2440) cost more than the table ever will.
