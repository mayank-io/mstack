---
name: finish-work-on-local-worktree
description: This skill should be used when the user says "finish worktree", "close out worktree", "merge and close milestone", "finish this worktree", "done with worktree", "wrap up worktree", or when a worktree branch is complete and needs to be merged into main AND related documentation status, project plan, and next-milestone recommendations need updating. Combines local merge (via git-worktree:local-merge), doc status updates, project plan updates, and next-milestone recommendation into one workflow. Prefer this over plain local-merge when doc and plan updates are needed.
version: 0.1.0
---

# Finish Work on Local Worktree

Complete a worktree lifecycle: squash-merge the branch into main, update all related documentation status, update the project plan, and recommend what to work on next.

## Prerequisites

- All tests pass on the worktree branch
- No uncommitted changes in the worktree
- Work on the branch is verified and ready to integrate

## Arguments

Accept an optional branch name argument. If not provided, detect from the current worktree or ask the user.

## Workflow

Execute these phases in order. Stop and report if any phase fails.

### Phase 1: Local Merge

Invoke the `git-worktree:local-merge` skill via the Skill tool, passing the branch name if provided as an argument.

Wait for the merge to complete before proceeding. If the merge fails (conflicts, dirty worktree, not in a worktree), stop and help the user resolve the issue.

After the merge succeeds, note the **BRANCH** name — it drives doc discovery in Phase 2.

### Phase 2: Update Related Documentation

Find all docs related to the merged branch and update their status to `completed`.

**Step 2a: Find related docs**

Use the Grep tool to search `docs/` for files whose YAML frontmatter contains `work: <BRANCH>` (substituting the actual branch name from Phase 1). Also check the `related:` frontmatter array in those docs to find transitively related docs.

**Step 2b: Update frontmatter status**

For each related doc found:

1. Read the current `status:` and `stage:` frontmatter fields
2. If `status:` is not already `completed`, update it to `completed`
3. If `stage:` exists, update it to `impl` (implementation is done)
4. Do NOT change docs that are already `completed` or `archived`

**Step 2c: Report changes**

List each doc updated with its old and new status:
```
Updated docs:
- docs/2026-04-04-feature-design.md: active → completed
- docs/2026-04-04-feature-impl-plan.md: active → completed
```

### Phase 3: Update Project Plan

Find and update the project plan to reflect the completed milestone. If no project plan is found, skip this phase entirely and note in the final report that no project plan was updated.

**Step 3a: Locate the project plan**

Search for the project plan file. Common patterns:
- `docs/project-plan*.md`
- A file with `type: impl-plan` or `type: project-plan` in frontmatter and `work: main`

**Step 3b: Identify the milestone**

Extract the milestone identifier from the branch name (e.g., `m5.7-tier1-conditions` maps to milestone M5.7). Search the project plan for the corresponding section header.

**Step 3c: Update milestone status**

In the project plan:

1. Append ` — COMPLETE` to the milestone section header if not already present
2. Add a `**Status: COMPLETE (<today's date>)**` line after the acceptance criteria
3. Strike through completed acceptance criteria with `~~criteria~~ Done` formatting
4. Add a `**What shipped:**` summary block listing key deliverables (read from the squash commit message and the related design/impl docs)
5. Update any lifecycle phase tracking tables (e.g., "AST and semantics" row) to reference the new milestone
6. If the milestone had an impl plan or design doc, add a `See [doc title](doc-path)` link

These formatting conventions assume the project plan follows the standard doc template. Adapt if the plan uses a different structure.

**Step 3d: Handle partially complete milestones**

If the branch only implemented part of a milestone (e.g., one stream of three):
- Do NOT mark the milestone as COMPLETE
- Update only the completed stream/section within the milestone
- Note which streams remain incomplete

### Phase 4: Recommend Next Work

Analyze the project plan to recommend what to work on next.

**Step 4a: Scan for next milestones**

Read the project plan and identify:
1. The next incomplete milestone after the one just completed
2. Any partially-complete milestones that have remaining streams
3. Any deferred items or known limitations noted in the completed milestone

**Step 4b: Present recommendation**

Format the recommendation as:

```
## What's Next

**Next milestones in order:**

| Milestone | What it adds |
|-----------|-------------|
| **M_X** | Brief description |
| **M_Y** | Brief description |

**Recommended:** M_X — [reason why this is the natural next step]
```

Include:
- Whether a design doc or impl plan already exists for the next milestone
- Any prerequisites or dependencies
- Deferred items from the just-completed milestone that feed into upcoming work

Do NOT include effort estimates or size labels unless the user explicitly requests them.

### Phase 5: Commit Doc Updates

Stage and commit all doc changes made in Phases 2-3. Adapt the commit message to reflect what was actually changed (doc statuses only, or doc statuses + project plan):

```bash
git add docs/
git commit -m "docs: mark <MILESTONE> complete, update project plan"
```

Do NOT add a Claude Code signature to the commit message.

## Rules

- Follow all `git-worktree:local-merge` rules during Phase 1 (no remote ops, no --no-verify, etc.)
- Never mark a milestone complete if the branch only covered part of it
- Never modify docs that are already `completed` or `archived`
- Always commit doc updates as a separate commit from the squash merge
- Present the next-work recommendation to the user — do not start working on it automatically
