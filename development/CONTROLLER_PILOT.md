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

The dispatcher uses two concurrent workers, one per role, nonoverlapping paths and dependency checks. Polls every 120 seconds when idle without model calls. Uses existing Codex ChatGPT session and bounded continuation. 120000 daily reserved tokens, 60000 per task, three rounds/20 minutes; reservation and measured token ceilings are soft and do not guarantee actual provider usage limits. No automatic merge, production deployment, trades or deletion. Draft PR publication checks scope, branch, base and file types. Draft PRs require independent review.

## Acceptance

Offline acceptance includes mocked GitHub/Codex flow and plist round-trip. Actual Mac launchd, authenticated GitHub push and real task-to-draft-PR readback must be confirmed before replacing existing hourly agents. Activate one reviewed task first, then transition other roles. No claim of live activation from CI alone.
