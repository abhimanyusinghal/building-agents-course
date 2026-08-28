---
service: checkout
doc_type: spec
version: 3.1
---
# Checkout API — payment validation (v3.1, superseded)

## Payment validation rules
Amounts are decimal strings with two fraction digits. Currency is a free-text
field validated downstream. Idempotency keys are optional and best-effort.
This version is superseded by v4.2; kept for services still on the old contract.
