As a support agent I want closed cases to show a read-only banner so that I do not type a long update into a case that can no longer be edited and lose it on save.

## Acceptance criteria

- Opening a case in status Closed shows a banner "This case is closed" above the note field.
- The note field on a closed case is read-only; paste and typing are rejected with the banner highlighted.
- Reopening the case removes the banner and restores editing without a page reload.

## Dependencies

- case-web.

## Rollback

Behind the closedCaseBanner flag, default off.
