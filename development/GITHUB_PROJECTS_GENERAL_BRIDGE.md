# ESCAPE Projects: general status bridge

This change prepares the existing Issue-comment → Actions → Projects → audit path for existing issues #1 and #3–#16 in `hva73/invest`, with Project `hva73/1`. The proposed write job and `LIVE_WRITE_ENABLED` both remain disabled. The owner has separately authorized one test: Issue #4 Backlog → In progress.

A future request is a new, unedited comment on the target Issue, from the verified user and GitHub App, starting with `ESCAPE_PROJECTS_WRITE_V1 ` and a JSON object containing exactly `request_id` (32 lower-case hex characters), `expected_status` and `desired_status`. Status values must be actual existing project Status options; the two values must differ. Issue #3 is limited to Backlog, In progress and In review until its owner-approved completion conditions are satisfied. This bridge never closes an Issue.

The validator obtains the target number from the authenticated GitHub event, verifies the comment, owner, project, unique active Project item and actual status. The writer rechecks identity and status, records one create-only journal claim bound to project/item/comment/transition, rechecks before one parameterized mutation, and reads back afterward. Audit and failure reports go to the same Issue, not to a new Issue. An uncertain result stops without automatic retry or rollback.

All cooperating workflows share the existing global concurrency group. `queue: max` allows up to 100 pending requests; additional runs can be canceled when full. Ordering is based on when runs enter the queue, not guaranteed dispatch order. GitHub's mutation does not support atomic expected-value comparison, so a simultaneous manual or external edit can still be overwritten; the owner has accepted this limited risk for reversible task statuses only.

Status before activation: generalized code and workflow are for review/test. The general writer remains disabled. The only enabled action in this change is the exact owner-approved #4 restoration. The change does not add Project items, create or close Issues, or touch production. A separately approved, one-shot workflow can restore #4 Backlog → In progress; no other board change is authorized by that approval. A real ChatGPT-origin request through the general bridge remains to be verified before Issue #11 can be closed.

## Verification

Forty-six local tests and [Actions run 42887779295](https://github.com/hva73/invest/actions/runs/42887779295) passed with synthetic Project responses and no Projects secret. Tests cover every allowed Issue number, correct Issue-to-item matching, same-Issue audit routing, unauthorized Issues, stale status, Issue #3 completion protection, Danish status names and simulated uncertain write outcomes. This is not a live multi-issue Projects mutation test. The PR validation run also exercised GitHub's `queue: max` workflow syntax.
