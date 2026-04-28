---
name: design-review-iterative
description: Run iterative design document review with diminishing fix thresholds. Use when the user says "review my design", "design review", "review this design doc", "review the design iteratively", or after completing a design document.
---

# Iterative Design Review

Run up to 4 review-fix iterations with 3 parallel reviewer agents (PE, Sr SDE, Domain Expert). Each iteration raises the bar for what gets fixed, converging quickly to a solid design.

## Review Scope

By default, review the most recently written or edited design doc in `docs/`. If the user specifies a file, use that instead.

## Process

### Step 0: Initialize

Set `iteration = 1`. Identify the design doc to review. Read it fully before launching reviewers.

### Step 1: Launch 3 Reviewer Agents in Parallel

Dispatch 3 agents simultaneously, each reviewing the same design doc from a different perspective. Every agent MUST categorize each finding as exactly one of: **BLOCKER**, **HIGH**, **MEDIUM**, **LOW**, **NIT**.

**Agent 1 — Principal Engineer (PE):**
> Review this design document as a Principal Engineer. Focus on: architectural soundness, scalability, extensibility, abstraction boundaries, coupling/cohesion, performance implications, operational complexity, security posture, and whether the approach will hold up under real-world load and evolution. Flag missing trade-off analysis, unclear decision rationale, and unaddressed failure modes. Categorize every finding as BLOCKER, HIGH, MEDIUM, LOW, or NIT.
>
> **Stay in your lane:** You own AST/IR representation, grammar ambiguity analysis, parser/compiler architecture, and performance. Do NOT rule on whether a domain concept is semantically valid — that is the Domain Expert's call. If you think a domain assumption is wrong, flag it as a question for the Domain Expert, not as a finding.

**Agent 2 — Senior SDE:**
> Review this design document as a Senior Software Engineer who will implement this. Focus on: implementation feasibility, missing technical details, gaps between design and codebase reality, unclear interfaces or contracts, missing error handling strategy, ambiguous naming, incomplete data flow, missing edge cases, and whether the milestones/tasks are actually achievable as scoped. Cross-reference with existing code patterns in the repo. Categorize every finding as BLOCKER, HIGH, MEDIUM, LOW, or NIT.
>
> **Stay in your lane:** You own implementation feasibility, code-level concerns, and codebase consistency. Do NOT rule on domain semantics or make assumptions about what is valid in the problem domain. If a design decision seems wrong but is labeled as domain-driven, flag it as a question for the Domain Expert rather than overriding it.

**Agent 3 — Domain Expert:**
> Review this design document as a domain expert for this project. Read CLAUDE.md and existing docs to understand the project context. Focus on: requirements completeness, whether the design actually solves the stated problem, missing use cases, incorrect assumptions about the domain, gaps in the testing strategy, missing rollback/migration concerns, and whether the milestones deliver testable value incrementally. Categorize every finding as BLOCKER, HIGH, MEDIUM, LOW, or NIT.
>
> **Stay in your lane:** You own domain correctness — whether the proposed syntax reads naturally, whether semantic assumptions match the domain reality, whether the right entities/concepts are modeled, and whether conditions are valid. Do NOT rule on parser implementation strategy, AST representation choices, or grammar ambiguity resolution — those are the PE's domain. If you see an implementation concern, flag it as a question for the PE.

### Step 2: Consolidate and Filter

Merge findings from all 3 agents. Deduplicate (same issue found by multiple reviewers = single finding at highest severity). Apply the fix threshold for the current iteration:

| Iteration | Fix Threshold                   | What Gets Fixed       |
| --------- | ------------------------------- | --------------------- |
| 1         | BLOCKER, HIGH, MEDIUM, LOW, NIT | Everything            |
| 2         | BLOCKER, HIGH, MEDIUM           | Skip LOW, NIT         |
| 3         | BLOCKER, HIGH                   | Skip MEDIUM and below |
| 4         | BLOCKER only                    | Skip HIGH and below   |

Present the consolidated findings to the user in a table:

```
## Design Review Iteration {N} — Findings

| # | Severity | Reviewer | Section | Finding | Fix? |
|---|----------|----------|---------|---------|------|
| 1 | BLOCKER  | PE       | Architecture | ... | Yes |
| 2 | HIGH     | Sr SDE   | Data Flow | ... | Yes |
| 3 | NIT      | Domain   | Milestones | ... | No (below threshold) |

Fixing N of M findings this iteration.
```

### Step 3: Fix

Apply all fixes at or above the threshold directly to the design document. For each fix:
- State which finding you're addressing
- Make the targeted edit to the relevant section
- If a finding requires a new section, add it in the appropriate place
- Preserve the document's existing structure and voice

### Step 4: Decide Next Iteration

Count how many findings were fixed this iteration.

- **If 0 fixes were made** → Done. Print summary and stop.
- **If fixes were made AND iteration < 4** → Set `iteration = iteration + 1`, go to Step 1.
- **If iteration = 4** → Done regardless. Print summary and stop.

### Step 5: Summary

When the loop exits, print:

```
## Design Review Complete

| Iteration | Findings | Fixed | Threshold |
|-----------|----------|-------|-----------|
| 1         | N        | N     | All       |
| 2         | N        | N     | MEDIUM+   |
| ...       | ...      | ...   | ...       |

Total iterations: N
Total findings: N
Total fixed: N
Remaining (below final threshold): N
```

Then update the design doc's frontmatter status from `draft` to `review` (if it was draft) or from `review` to `active` (if review is complete with no remaining blockers).
