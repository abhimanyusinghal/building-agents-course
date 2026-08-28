---
service: auth
doc_type: runbook
version: 1.1
---
# Auth service — incident runbook

## Login failure spike
Check the throttle dashboard first: a spike of ERR_AUTH_1042 usually means a
client retry loop, not an outage. Confirm Retry-After is present on 429s; a
missing header turns a throttle into a storm. Escalate to the identity provider
only when SSO redirects (302) are also failing.
