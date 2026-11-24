# ESCAPE Development Controller — pilot (#225)

Purpose: execute the next repair round immediately, without waiting for a ChatGPT hourly task. This is an isolated, manually launched pilot, not a production service or a remote control of existing conversations.

## Local dry run and tests (no API)
From a fresh clone on a disposable controller/ branch:
```sh
python -m unittest discover -s tests -p test_controller_pilot.py
python development/controller_pilot.py --role mobile --issue 54 --task-file /tmp/escape-task.txt
```
The task file must contain a reviewed, specific issue scope. A dry run makes no model call.

## Paid pilot (not yet authorized with a budget)
Install the official Codex CLI, use a fresh isolated OS/container environment and clone with no broker/production secrets, no SSH agent, no stored GitHub credentials, no shared HOME. Disable network for agent shell commands using the Codex sandbox; permit required model access. Put a dedicated, restricted API key in the environment through a secret manager. Do not paste it in a chat or commit. Set an externally enforced spending limit or monitor and cancel; the script's call/time ceilings are not a dollar limit. Pause the existing corresponding hourly agent for the selected issue before running.

```sh
git switch -c controller/mobile-54
python development/controller_pilot.py --role mobile --issue 54 --task-file /tmp/escape-task.txt --rounds 3 --minutes 20 --execute
```
Each successful invocation with changed worktree starts the next immediately. No changes, repeated state, execution error, time or round limit stops the pilot. Fresh calls inspect the same worktree; no promise of existing chat session continuity. No automatic commits, PR, merges, deployment or trade. Inspect diff and independently run targeted tests before publishing.

## Next acceptance gate
Verify actual CLI syntax/version, sandbox isolation and API authentication in the intended runner. Measure token/cost, useful changes and repeated states on one issue. Then add trusted issue queue, per-role isolated checkouts and locks, independent tests and controlled PR publishing. Only after pilot acceptance replace hourly agents. Do not run on Nordicway production or add production secrets. GitHub Actions runner integration and autonomous queue are not implemented in this pilot.
