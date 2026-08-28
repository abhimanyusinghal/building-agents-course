---
service: auth
doc_type: spec
version: 2.3
---
# Authentication service — functional spec

## Password reset — token rules
A password reset token is valid for 45 minutes from issue. A token is single-use:
once redeemed it is dead, even inside the 45-minute window. An account may request
at most three password resets per calendar day; the fourth request in a day is
refused with HTTP 429.

## Password reset — SSO-managed accounts
Accounts provisioned through SSO have no local password. A reset request for an
SSO-managed account is not an error: the service answers 302 and redirects the
user to the identity provider. No reset e-mail is sent.

## Login throttling
Authentication requests are throttled after five failed attempts within ten
minutes for the same account. Throttled callers receive HTTP 429 with error code
ERR_AUTH_1042 in the body and a Retry-After header. The throttle clears 15
minutes after the last failed attempt.

## E-mail address handling
E-mail addresses are stored lowercase and all lookups must be case-insensitive.
See INC-2214 for the outage caused when reset lookups were case-sensitive.
