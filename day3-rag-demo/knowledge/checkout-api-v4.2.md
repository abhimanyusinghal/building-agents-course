---
service: checkout
doc_type: spec
version: 4.2
---
# Checkout API — payment validation (v4.2)

## Payment validation rules
Amounts are integers in minor units; a float anywhere in the money path is a
defect. Currency must be an uppercase ISO-4217 code. Every POST /payments carries
an Idempotency-Key header; a repeated key returns the original result, not a new
charge. A checkout may hold at most three payment instruments.

## Refund rules
A refund never exceeds the captured amount, and refunds against a voided payment
are refused with 409.
