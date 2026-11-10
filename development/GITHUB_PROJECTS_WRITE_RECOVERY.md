# Projects writer: conflict and uncertain-result recovery

This applies only after a future writer is separately reviewed, enabled and explicitly approved for its first real test. The current prototype and proposed workflow are disabled.

## State handling

- Before a claim, a stale status, invalid request or inaccessible Project blocks without mutation. A newly checked request can be submitted later using a **new** request ID.
- After a claim but before a mutation, any validation, status or metadata mismatch stops. Preserve the claim; never delete or recreate it to make the same request run again.
- Once a mutation was submitted, timeout, invalid response, missing audit, failed readback or a mismatch is **uncertain**. Never retry the same request, never automatically roll back, and never infer success from an HTTP error or claim alone.
- A verified readback is evidence of the state at the time of that read. It is not proof that an independent human change could not have been overwritten between the preceding read and the mutation.

## Reconciliation

1. Pause new writes through every cooperating writer. Do not alter the journal, workflow or Project item as a diagnostic step.
2. Inspect the authenticated request comment and its edit history, claim history, workflow run/attempt and Issue audit. Do not print credentials or raw authenticated responses.
3. Independently read the exact project owner, number, item ID, issue, status field and current status. Confirm the writer's intended transition and whether another writer or human could have acted in the interval.
4. Record the evidence and uncertainty on Issue #4 and #11. A claim proves registration, not that a mutation occurred. The current card showing either old or desired status alone does not prove the intermediate history.
5. If evidence does not resolve the incident, keep writes paused and obtain a deliberate owner decision. After reconciliation, any further change is a **new**, separately validated request; the original ID remains consumed. A first real Project mutation still requires explicit separate owner approval.

This process must be tested before activation, including an audit outage and crash after claim or mutation. It does not solve GitHub's lack of an atomic expected-status condition.
