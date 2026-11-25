# ESCAPE Development Controller

## Installation on the existing Mac clone

Requires macOS, Python 3.9+, existing Codex ChatGPT login, GitHub CLI (gh) authenticated for hva73/invest. No API key required. Use a dedicated development machine/account without production or broker credentials.

```sh
cd ~/ESCAPE-Development/controller
git fetch origin codex/development-controller-pilot
git switch --detach origin/codex/development-controller-pilot
python3 -m unittest discover -s tests -p 'test_controller_*.py'
python3 development/controller_mac.py install --publish
```

If gh is missing install it from https://cli.github.com/ and run gh auth login. Installer checks authentication, reads the trusted queue, runs offline tests and installs a per-user LaunchAgent. Runs after login, restarts on failure. No root privileges. The Mac must remain awake and logged in.

## Operations

```sh
python3 development/controller_mac.py status
tail -n 50 ~/ESCAPE-Development/runtime/service.log
python3 development/controller_mac.py stop
```

Stop creates STOP sentinel and unloads the LaunchAgent. Inspect results.json, budget.json, generation-specific .log/.patch/.pr files in runtime. Do not remove old checkouts blindly. Install without --publish for local patches only.

## Queue

Coordinator edits development/controller_tasks.json on codex/development-controller-pilot via GitHub. Queue initially empty. Each task specifies issue (open issue), role (release/mobile/motor/data/desktop), priority (integer; lower first), status (ready/active/done/blocked), paths (explicit allowed files), dependencies (issue IDs), generation (positive integer), base_branch (codex/escape-development), base_sha (exact 40-character current branch head), and task (reviewed scope). Increment generation for a new attempt after review. Mark done only after independent verification. No automatic retries of failed generations. Do not assign the same issue to hourly agents and controller simultaneously.

The dispatcher uses two concurrent workers, one per role, nonoverlapping paths and dependency checks. Polls every 120 seconds when idle without model calls. Uses existing Codex ChatGPT session and bounded continuation. No default daily reservation cap; optional local cap, 60000 uncached-plus-output tokens per task when reported (gross fallback), three rounds/20 minutes. The soft continuation threshold is not a provider billing or quota measure. A verified agent draft-ready marker with scope check stops redundant rounds. Explicit provider limit pauses new work; resume only at a reported reset time, otherwise require confirmed recovery. Multiple generations per issue may be preapproved; dependencies use issue:generation and must be explicitly reviewed/done. The controller starts the next eligible independent task as a worker frees up; it does not wait for a slow unrelated worker. A context-length failure permits one fresh session on the preserved worktree, with original task scope. Checkpoints and original task files stay local. After a confirmed new OS boot, an interrupted reservation with unchanged approved task, no terminal receipt, and no previous recovery can resume once on the original scoped checkout; a clean reservation can restart. Same-boot crashes, changed tasks, unknown boot identity, publication commits and provider limits remain blocked for coordinator review. The existing checkout and checkpoints are preserved. Live STARTED/WORKING/TESTING/CONTINUING/HANDOVER/review/block notifications are based on observed events, not completion claims. No automatic merge, production deployment, trades or deletion. Draft PR publication checks scope, branch, base and file types. Draft PRs require independent review.

## Acceptance

Offline acceptance includes mocked GitHub/Codex flow and plist round-trip. Actual Mac launchd, authenticated GitHub push and real task-to-draft-PR readback must be confirmed before replacing existing hourly agents. Activate one reviewed task first, then transition other roles. No claim of live activation from CI alone.

## Release pilot safety and lifecycle

Only exact coordinator-approved release-client files may be published by the release role, and only to a draft PR. No server guard, deployment workflow or credentials are accessible to the model under this mandate. Keep independent review before integration; a draft is not a completed main issue. The controller posts deduplicated progress and delivery receipts to GitHub; ChatGPT coordinator delivery still follows its scheduled runs. Install only when no task is running. A provider pause with unknown reset requires actual account recovery confirmation before clearing the local pause file; never bypass the provider limit.
