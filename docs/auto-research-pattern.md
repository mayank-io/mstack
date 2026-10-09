# Auto-Research Loops

**Trigger:** When the user says "auto-research loop", "autoresearch", "auto research",
or describes systematic hypothesis testing across a menu of dimensions / parameter
sweeps / experiments (especially science, trading, ML, data exploration), use this
pattern. Read this file before building anything.

**Reference:** https://github.com/karpathy/autoresearch

## Core principle

**The agent is the orchestrator, not Python code.** Do NOT build a YAML registry
plus handler-dispatch framework. That bakes in inflexibility — every novel
hypothesis needs a new handler. Instead, build a `program.md` that instructs an
agent on the loop. The agent walks the hypothesis menu and runs each test using
existing analysis primitives. The "code" the human edits is the markdown
instructions, not the runner.

## Required architecture

Three artifact types:

1. **Primitives** — existing scripts / modules that perform analysis. Read-only
   from the loop's perspective. The agent extends with new flags but does not
   fork or rewrite.
2. **`program.md`** — human-edited; instructs the agent on procedure, methodology,
   logging, and stop conditions.
3. **Log directory** — append-only master log (CSV) plus per-run writeups
   (markdown + params.json + raw output).

Layout:

```
<project>/
├── analysis/                    # or domain-specific name — primitives live here
├── docs/<dimensions>.md         # the hypothesis menu (user maintains this)
└── analysis/research/
    ├── program.md               # the agent's program
    └── log/
        ├── research_log.csv     # master append-only log
        └── runs/<run-id>/       # per-iteration artifacts
            ├── writeup.md
            ├── params.json
            └── *.csv
```

## Required elements in program.md

1. **Mission statement** — what's being tested; emphasize honest characterization,
   not validation.
2. **What the agent edits / produces** — explicit allowed paths.
3. **What the agent does NOT modify** — read-only paths (data, primitives, this
   program, project memory).
4. **Per-iteration procedure**:
   read state → select next hypothesis → pre-register H0/H1 + effect direction
   → run → decide (`supported` / `rejected` / `inconclusive`) → log → iterate.
5. **Selection rule** (priority order):
   1. Highest expected information gain — the next test should confirm or kill
      the most surprising prior finding cheaply.
   2. Independence from already-tested confounds.
   3. Runnable today — skip blocked deps and record them as `status=blocked`
      with the missing dep in `notes`.
   4. Cheap-first within a tier.
6. **Evaluation methodology** by metric type:
   - Threshold rates → chi-squared vs. matched-control (or strict non-window base)
   - Continuous magnitudes → t-test or Mann-Whitney U vs. matched-control
   - Direction counts → binomial test
   - Time-series stability → per-period sweep + visual inspection
7. **Multiple-testing correction** — always report raw p AND Bonferroni-corrected
   p. Multiplier = count of *runnable* hypotheses (recompute as the count
   changes; reflect on every row).
8. **Sample-size guardrails (non-negotiable)**:
   - Any cell with `n < 30` → never `supported`; use
     `inconclusive: insufficient sample`.
   - Smallest cell `n < 10` → don't run; mark `blocked` with reason.
9. **Run-ID format**: `<seq>-<YYYYMMDD-HHMMSS>-<hypothesis-id>` (4-digit zero-padded
   monotonic seq, UTC timestamp, kebab-case hypothesis slug).
10. **Master log CSV schema** — minimum columns:
    `run_id, hypothesis_id, hypothesis_name, class, started_at, status, n_obs,
    primary_metric, effect, p_raw, p_bonferroni, supported, writeup_path, notes`.
11. **Project conventions** — inherit from CLAUDE.md and project memory
    (cents/paise units, City (Country) place form, table format conventions,
    logs-stay-clean, etc.).
12. **Stop conditions**:
    - All runnable hypotheses tested → emit final report, stop.
    - Bonferroni-significant finding (`p_bonf < 0.05`) → flag as priority,
      run *one* immediate confirmatory test (different metric or different
      time slice), then pause for human review.
    - More than 50% of remaining hypotheses share the same blocker → pause,
      emit "needs unblock" report.
    - 3 consecutive `error` statuses → pause, emit debugging report.

## Loop driver

The `ralph-loop` plugin is the standard way to run unattended iterations.
One ralph-loop tick = one hypothesis tested + logged. Prompt template:

```
/ralph-loop "Read <project>/analysis/research/program.md and run one iteration. Then stop."
```

Karpathy's pacing: ~12 iterations/hour, ~100 overnight on a single GPU box.
For markdown-driven research the cadence depends on hypothesis cost; estimate
during the first few iterations.

## What "good" looks like

- Each iteration's writeup is reproducible from `params.json` alone.
- The log lets a reader scan 10 rows and form an honest picture of what's
  known. No inflated claims; no buried negatives.
- A reader six months from now can re-run any iteration with one command.
- The cumulative log shows decreasing surprise as the experiment matures —
  i.e. the loop is building knowledge, not just running tests.

## Reference implementation

The astro/stock correlation project has a working program.md to copy/adapt:

```
/Users/mayank/Developer/projects/stock-trading-usa/astro-stock-analysis/analysis/research/program.md
```

The hypothesis menu it consumes:

```
/Users/mayank/Developer/projects/stock-trading-usa/astro-stock-analysis/docs/analysis-dimensions.md
```

## Common pitfalls to avoid

- **Don't build the runner in Python.** It will become rigid and bloated as
  hypotheses diversify. The whole point of this pattern is that the agent
  adapts the test design per hypothesis from primitives.
- **Don't hardcode the hypothesis registry in YAML.** Let the menu live as
  prose in a markdown doc the user already maintains. Single source of truth.
- **Don't skip the sample-size guardrails.** Without them, the log fills with
  phantom findings from cells of n=3.
- **Don't pretend the Bonferroni multiplier is fixed.** If hypotheses get added
  or unblocked mid-experiment, recompute and update. The "running multiplier"
  is technically optimistic but it's a more honest fix than a stale fixed value.
- **Don't run the loop in foreground inside the assistant.** Use ralph-loop or
  similar — keeps the assistant's context clean and lets the user intervene.
- **Don't forget the selection rule.** A naive "walk the list in order" loop
  produces the least informative log. The "highest expected information gain"
  rule is what turns a research log into a research *process*.
