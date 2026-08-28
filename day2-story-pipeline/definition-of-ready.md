# Definition of Ready

A story is Ready when a team member who was not in refinement could pick it up and
start work without asking a question. Refinement checks all seven. A story that fails
any one of them is not Ready, and the missing item is named in the refinement comment.

## 1. Problem statement

States who has the problem, what they cannot do today, and why it matters now.
"As a … I want … so that …" is acceptable but the *so that* has to name a real
consequence, not restate the want.

## 2. Acceptance criteria

Every behaviour described in the story has at least one acceptance criterion that can
be observed and tested by somebody other than the author.

A criterion is **not** testable if it relies on any of: *appropriate, reasonable,
sensible, user-friendly, performant, as needed, where relevant, properly, correctly
handled*. These words move the judgement to whoever tests it, which is exactly the
argument the criterion was supposed to settle.

## 3. Dependencies

Every system the story reads from or writes to is named, using the component name from
the service catalogue. "The orders system" is not a component name; `orders-api` is.

## 4. Non-functional expectations

Where the story touches a user-facing screen or a shared service, at least one number:
a response-time target, an expected volume, or a retention period. A number that turns
out to be wrong is still better than no number, because it can be argued with.

## 5. Data

If the story causes personal data to be read, stored, or displayed, the categories of
data are listed and a retention period is stated. Order history, contact details and
payment metadata all count as personal data here.

## 6. Sizing

Estimated by at least two people, and no larger than one sprint. A story nobody will
size is a story nobody understands.

## 7. Rollback

If the change is visible to a user, the story says how it is turned off — a flag, a
configuration value, or a documented revert. "Redeploy the previous version" is only
acceptable where there is no data migration.
