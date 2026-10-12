---
name: safe-resume
description: Use when the user says "safe resume", "resume from pause", "pick up where we left off", "continue the paused work", or when a session start hook reports a /dev:safe-pause state for this session. Also use when a fresh session is asked to continue and a RESUME.md exists for it.
---

# Safe Resume

Continue exactly where `/dev:safe-pause` stopped, in the recorded order, at the recorded boundary, without asking what was happening.

`PS` below is `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/pause_state.py` (run `--help` for the subcommands).

## Procedure

1. **Locate.** `PS locate --session-id <id> --cwd <repo>`. The id is `$CLAUDE_SESSION_ID` when set, else the id in this session's scratchpad path. No output and exit 1 means there is no pause state: say so in one line and continue with the normal session resume. Do not invent a state.
2. **Read** the RESUME.md it prints, frontmatter and body, in full.
3. **Verify every worktree.** `PS verify --resume <path>`. Exit 0 means every recorded worktree is present, at its recorded tip, and clean. Exit 2 means it is not: stop, repeat the lines it printed naming each worktree and why (`tip-moved`, `dirty`, `missing`), and do not continue. Only MK can decide what to do with a moved tip.
4. **Re-send the first message** from `## First message`, and only if the frontmatter records a `coordinator`. No coordinator: send nothing to anyone.
5. **Run the first command** from `## First command`, exactly as written.
6. **Mark consumed.** `PS mark-resumed --resume <path>` so the session-start hook stops announcing it.
7. **Continue** in the recorded order: in-flight branches first at their owed step, then the queue. Honour the recorded mode's boundary semantics as `/dev:safe-pause` defines them. Blockers stay blocked until the recorded holder clears them.

## Rules

- Never continue past a failed verify. A moved tip means someone else worked here; a dirty tree means a commit was skipped.
- Never re-run a step RESUME.md records as passed. Only owed steps are run.
- Never message a peer the frontmatter does not name.
- The `Peer messages logged` section is the backlog of who was told `PAUSED`; tell each of them the session has resumed, once, in your first message to them.
