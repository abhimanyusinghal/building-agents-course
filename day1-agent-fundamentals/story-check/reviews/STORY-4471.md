# Not Ready: STORY-4471 is not ready to be picked up.

- DoR-1: Pass. The story states who has the problem, what they cannot do today, and why it matters now: `As a support agent I want to see a customer's recent orders on the case screen so that I do not have to switch systems while the customer is on the phone.`

- DoR-2: Fail. The acceptance criteria are not observable and testable. `Performance should be reasonable`, `Only appropriate customer data is displayed`, and `The panel is user-friendly` rely on subjective judgement and do not define an observable outcome.

- DoR-3: Fail. The dependency is not named with a component name from the service catalogue. `The orders system` and `orders service` are not component names; the story must name the actual dependency, such as `orders-api`.

- DoR-4: Fail. The story touches a user-facing screen but sets no numeric target. `Performance should be reasonable` is not a measurable target; it needs a response-time goal, expected volume, or similar number.

- DoR-5: Fail. The story does not list the personal data categories or a retention period. The notes mention `email address`, but there is no statement of which categories are read or displayed and how long they will be kept.

- DoR-6: Fail. There is no sizing evidence. `Sprint: unassigned` indicates the story has not been estimated by at least two people and is therefore not sized.

- DoR-7: Fail. The user-visible change is not described with a rollback mechanism. The story says `Recent orders are shown on the case screen`, but it does not say how the feature is turned off with a flag, configuration value, or documented revert.
