---
name: ml-design-review-iterative
description: Run iterative ML design review with diminishing fix thresholds. Use when reviewing designs for ML systems, evaluation harnesses, automated search systems, scoring functions, data pipelines, or any design where statistical soundness, data leakage, overfitting risks, and metric validity are primary concerns.
---

# Iterative ML Design Review

Run up to 4 review-fix iterations with 3 parallel reviewer agents (Principal ML Engineer, Sr Applied Scientist, ML Ops Engineer). Each iteration raises the bar for what gets fixed, converging quickly to a statistically sound and practically deployable design.

## Review Scope

By default, review the most recently written or edited design doc in `docs/`. If the user specifies a file, use that instead.

## Process

### Step 0: Initialize

Set `iteration = 1`. Identify the design doc to review. Read it fully before launching reviewers. Also read CLAUDE.md and any referenced prior designs or experiment logs to understand the project context.

### Step 1: Launch 3 Reviewer Agents in Parallel

Dispatch 3 agents simultaneously, each reviewing the same design doc from a different perspective. Every agent MUST:
- Research relevant frameworks, papers, or tools mentioned in the design (use web search)
- Categorize each finding as exactly one of: **BLOCKER**, **HIGH**, **MEDIUM**, **LOW**, **NIT**
- Include a confidence score (0-100) for each finding

**Agent 1 — Principal ML Engineer:**
> Review this design document as a Principal ML Engineer with deep experience in AutoML, neural architecture search, and automated research systems. Focus on: evaluation methodology soundness, metric design (can the optimization target be Goodharted?), overfitting risks given the dataset size, data leakage vectors, search space design, whether the evaluation is deterministic and reproducible, whether baselines are sufficient to validate the harness, and whether the system will actually find real signal vs. noise. Research any referenced frameworks (e.g., autoresearch, optuna, ray tune) to verify the design faithfully adapts their principles. Categorize every finding as BLOCKER, HIGH, MEDIUM, LOW, or NIT with a confidence score.
>
> **Stay in your lane:** You own ML methodology, evaluation design, and search architecture. Do NOT rule on domain-specific assumptions about the data (e.g., whether a financial feature is meaningful) — that is the Applied Scientist's domain. Do NOT rule on infrastructure choices — that is ML Ops' domain. If you see a concern outside your lane, flag it as a question for the relevant reviewer.

**Agent 2 — Senior Applied Scientist:**
> Review this design document as a Senior Applied Scientist with expertise in quantitative finance, backtesting methodology, and statistical validation. Focus on: statistical power of the evaluation (is N large enough?), walk-forward / cross-validation methodology, multiple comparisons bias, constraint calibration (are thresholds well-chosen or arbitrary?), whether the scoring function rewards real edge vs. artifacts, fill model realism, temporal split correctness, feature leakage risks, and whether the design accounts for non-stationarity in financial data. Verify claims about dataset size, available features, and existing infrastructure against the actual codebase. Categorize every finding as BLOCKER, HIGH, MEDIUM, LOW, or NIT with a confidence score.
>
> **Stay in your lane:** You own statistical methodology, domain data assumptions, and quantitative correctness. Do NOT rule on ML architecture choices (model selection, search space design) — that is the Principal ML Engineer's domain. Do NOT rule on deployment infrastructure — that is ML Ops' domain. If you see a concern outside your lane, flag it as a question for the relevant reviewer.

**Agent 3 — ML Ops / Production Engineer:**
> Review this design document as an ML Ops Engineer who will deploy and monitor this system. Focus on: reproducibility (can results be recreated?), experiment tracking and versioning, compute budget and wall-clock constraints, failure modes and recovery (what happens when strategy.py crashes?), data pipeline reliability, result storage and querying, how the human reviews and approves candidates, monitoring for the autonomous loop, and whether the system degrades gracefully under edge cases (empty data days, NaN features, zero trades). Categorize every finding as BLOCKER, HIGH, MEDIUM, LOW, or NIT with a confidence score.
>
> **Stay in your lane:** You own deployment, monitoring, infrastructure, and operational concerns. Do NOT rule on ML methodology (model choice, evaluation design) — that is the Principal ML Engineer's domain. Do NOT rule on statistical validity — that is the Applied Scientist's domain. If you see a concern outside your lane, flag it as a question for the relevant reviewer.

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
## ML Design Review Iteration {N} — Findings

| # | Severity | Confidence | Reviewer | Section | Finding | Fix? |
|---|----------|------------|----------|---------|---------|------|
| 1 | BLOCKER  | 95         | ML Eng   | Scoring | ... | Yes |
| 2 | HIGH     | 88         | Appl Sci | Walk-Forward | ... | Yes |
| 3 | NIT      | 70         | ML Ops   | Tracking | ... | No (below threshold) |

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
## ML Design Review Complete

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
