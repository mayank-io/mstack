---
name: code-review-iterative
description: Run iterative code review with diminishing fix thresholds. Use when the user says "review my code", "iterative review", "code review", "review this iteratively", or after completing a feature implementation.
---

# Iterative Code Review

Run up to 4 review-fix iterations with 3 parallel reviewer agents (PE, Sr SDE, QA). Each iteration raises the bar for what gets fixed, converging quickly to clean code.

## Review Scope

By default, review unstaged changes from `git diff`. If the user specifies files, a branch, or a PR, use that scope instead.

## Process

### Step 0: Initialize

Set `iteration = 1`. Determine the review scope (git diff, specific files, or user-specified).

### Step 1: Launch 3 Reviewer Agents in Parallel

Dispatch 3 agents simultaneously, each reviewing the same code from a different perspective. Every agent MUST categorize each finding as exactly one of: **BLOCKER**, **HIGH**, **MEDIUM**, **LOW**, **NIT**.

**Agent 1 — Principal Engineer (PE):**
> Review this code as a Principal Engineer. Focus on: architecture, design patterns, abstraction quality, API contracts, performance implications, scalability concerns, and whether the approach is fundamentally sound. Categorize every finding as BLOCKER, HIGH, MEDIUM, LOW, or NIT. Include file path and line number for each.
>
> **Stay in your lane:** You own architecture, AST/IR design, parser/compiler structure, and performance. Do NOT rule on whether a domain concept is semantically valid or whether a condition should accept certain inputs from a domain perspective — that is the Domain Expert's call. If you think a domain assumption in the code is wrong, flag it as a question rather than a finding.

**Agent 2 — Senior SDE:**
> Review this code as a Senior Software Engineer. Focus on: correctness, edge cases, error handling, null/undefined safety, race conditions, resource leaks, naming, readability, DRY violations, and adherence to project conventions (check CLAUDE.md). Categorize every finding as BLOCKER, HIGH, MEDIUM, LOW, or NIT. Include file path and line number for each.
>
> **Stay in your lane:** You own implementation correctness, code quality, and codebase consistency. Do NOT rule on domain semantics or override domain-driven design decisions. If a pattern seems wrong but is documented as a domain requirement, flag it as a question rather than a finding.

**Agent 3 — QA Engineer:**
> Review this code as a QA Engineer. Focus on: test coverage gaps, untested edge cases, missing error path tests, input validation, integration risks, regression potential, and observable behavior correctness. Categorize every finding as BLOCKER, HIGH, MEDIUM, LOW, or NIT. Include file path and line number for each.
>
> **Stay in your lane:** You own test coverage, test quality, and behavioral correctness. Do NOT rule on architectural decisions or domain semantics. If you see missing test cases that depend on domain knowledge (e.g., "should this condition accept lord references?"), flag it as a question for the Domain Expert rather than asserting the answer.

### Step 2: Consolidate and Filter

Merge findings from all 3 agents. Deduplicate (same issue found by multiple reviewers = single finding at highest severity). Apply the fix threshold for the current iteration:

| Iteration | Fix Threshold | What Gets Fixed |
|-----------|--------------|-----------------|
| 1 | BLOCKER, HIGH, MEDIUM, LOW, NIT | Everything |
| 2 | BLOCKER, HIGH, MEDIUM | Skip LOW, NIT |
| 3 | BLOCKER, HIGH | Skip MEDIUM and below |
| 4 | BLOCKER only | Skip HIGH and below |

Present the consolidated findings to the user in a table:

```
## Review Iteration {N} — Findings

| # | Severity | Reviewer | File:Line | Finding | Fix? |
|---|----------|----------|-----------|---------|------|
| 1 | BLOCKER  | PE       | src/x.rs:45 | ... | Yes |
| 2 | HIGH     | Sr SDE   | src/y.rs:12 | ... | Yes |
| 3 | NIT      | QA       | src/z.rs:99 | ... | No (below threshold) |

Fixing N of M findings this iteration.
```

### Step 3: Fix

Implement all fixes at or above the threshold. For each fix:
- State which finding you're addressing
- Make the minimal change needed
- Do not refactor unrelated code

### Step 4: Decide Next Iteration

Count how many findings were fixed this iteration.

- **If 0 fixes were made** → Done. Print summary and stop.
- **If fixes were made AND iteration < 4** → Set `iteration = iteration + 1`, go to Step 1.
- **If iteration = 4** → Done regardless. Print summary and stop.

### Step 5: Summary

When the loop exits, print:

```
## Review Complete

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
