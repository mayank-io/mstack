---
name: safe-pause
description: Use when the user says "safe pause", "pause safely", "bring this to a stop", "wind down", "stop at the next boundary", or wants a running session and its subagents brought to a resumable stop at a task, milestone or project boundary. Also for "pause now" when work must stop at the last green point.
---

# Safe Pause

Bring this session and every subagent it owns to a stop that `/dev:safe-resume` can continue from without asking what was happening.

**Violating the letter of these rules is violating their spirit.** A pause that leaves one worktree dirty, pushes one branch, or forgets one owed step is not a pause.

## Arguments

`/dev:safe-pause [task|milestone|project] [--now]`. Default `task`.

| Mode | Stop point | While running down |
|------|-----------|--------------------|
| `task` | Each live subagent finishes the unit it is on (the commit, the test run, the review pass), commits, writes its resume memory, exits. Bound ~20 min. `--now`: stop at the last green point instead of finishing the unit. | Session exits once the last subagent has. |
| `milestone` | Agents run to the end of the current milestone as its plan defines it: all its commits, its targeted tests, its review, READY reported. The next milestone is not started. | Session stays up to orchestrate, declines anything new, prints a progress line every 30 min. |
| `project` | The session completes the whole dispatched item: every milestone through LAND READY, and LANDED where a lander session exists. | Nothing new accepted during the run-down. |

## Invariants (every mode)

- No new dispatch or backlog item is taken from the moment the skill starts.
- Peer messages that arrive are answered `PAUSED (<mode>), resumes on MK's word` and logged into RESUME.md under *Peer messages logged*.
- Every worktree this session or its agents own ends with a commit. If the work is not a real commit, make a labelled one: `wip(pause): <what is built> / <what is owed>`.
- Nothing pushed, merged or landed. Never touch a primary main.
- One-full-suite rule: do not start a full suite to "finish". A suite already running may complete.
- Resume memory goes to `~/.local/state/mk-pause/<session-name>/RESUME.md`. Never `/tmp`.

## Procedure

Use `bash` with `set -euo pipefail` and `"${VAR:?}"` for every path variable. `PS` below is `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pause_state.py` (run `--help` for the subcommands).

1. **Freeze intake.** Record the mode and the wall-clock time. From here on decline new work.
2. **Detect topology, do not assume it.** The session has a coordinator only if its config or memory names a PM, or `ListAgents` shows a peer it has already exchanged messages with. Note the lander the same way. A session that runs independently reports to MK only.
3. **Signal every live subagent** with the mode. In `task` mode each one finishes its unit (or, with `--now`, stops at its last green point), commits, writes its own `RESUME.md` section (branch, worktree, tip, tests passed and owed, review state, exact next command), and exits. In `milestone` and `project` modes keep orchestrating until the mode's stop point, then do the same.
4. **Make every owned worktree clean.** List the session's repos (every repo it or its agents worked in) and the branches it owns. `PS dirty --repo <repo> [--repo <repo2>] --owned <branch> [--owned <branch2>]` lists what is still dirty. In each listed worktree commit the real work or a `wip(pause): <built> / <owed>` commit. Repeat until `dirty` exits 0. The primary checkout is never listed and never committed on: files already there, whoever left them, are recorded as a baseline instead.
5. **Write the resume body** to a scratch file with these sections, in this order:
   - `## First message` — the exact text to re-send to the coordinator on resume, or `none`.
   - `## First command` — the single exact command to run first on resume.
   - `## In-flight` — one bullet per branch: worktree, tip, tests passed, tests owed, review state.
   - `## Queue` — remaining work in order.
   - `## Blockers` — each with who holds it.
   - `## Subagents` — each subagent's section from step 3.
   - `## Peer messages logged` — every message acknowledged during the run-down.
6. **Record the state.** `PS write --session <session-name> --session-id <id> --mode <mode> --repo <repo> [--repo <repo2>] --owned <branch> [--owned <branch2>] --body <file> [--coordinator <name>] [--lander <name>]`. Pass every repo the session touched, so resume verifies all of them. Pass `--owned` for each branch (or worktree path) the session owns; without it every non-primary worktree is treated as the session's, including other sessions'. It records each owned worktree's branch and tip, records each primary checkout as a baseline, and refuses while an owned worktree is dirty or an `--owned` name matches nothing. The session name is the one set with `/rename`; the id is `$CLAUDE_SESSION_ID` when set, else the id in this session's scratchpad path.
7. **Pointer in auto-memory.** Add one line to this project's `MEMORY.md`: `- [Paused <session-name>](...) — resume via /dev:safe-resume, state at <RESUME.md path>`.
8. **Report, by topology.** Coordinator present: send the pause report (mode, time, branches with tips, owed steps, RESUME.md path) to the PM, and to the lander if one of the branches is queued there. No coordinator: report to MK in the terminal only; RESUME.md already holds it. Never message a peer this session has never talked to. Never broadcast.
9. **Stop.** `task`: exit when the last subagent has. `milestone`: stop after READY is reported, session stays up. `project`: stop after LAND READY (or LANDED).

## Red Flags: stop, you are not paused

- "I'll push this one branch so it isn't lost" → nothing is pushed. The commit is the safety.
- "The suite will only take a few minutes" → no suite is started to finish.
- "This dispatch is tiny, I'll take it" → intake is frozen.
- "I'll write RESUME.md from memory later" → write it before exiting; `PS write` refuses dirty owned worktrees for this reason.
- "The tool refused, so I'll record a different repo instead" → no. Pass every repo with `--repo` and the session's branches with `--owned`; a refusal names an owned worktree to commit.
- "The PM probably wants to know" when no PM has been talked to → report to MK only.
