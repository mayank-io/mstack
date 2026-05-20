---
name: next-idea
description: "Propose the single smartest, most radically innovative, accretive, useful, and compelling addition to the current project. Output uses BLUF + Pyramid Principle. Use when the user says \"next idea\", \"what should I build next\", \"what's the best next move\", \"what would make this 10x better\", or wants a single high-conviction recommendation grounded in the current state of the project."
---

# Next Idea

Identify the **single** highest-leverage addition the project could make right now. Not a list, not a roadmap — one idea, fully argued.

## The Question

> What's the single smartest and most radically innovative and accretive and useful and compelling addition you could make to the project at this point?

## Procedure

1. **Ground yourself in the project.** Before generating ideas, read enough of the repository to know what exists. At minimum: top-level `README.md`, the directory structure, any `CLAUDE.md` / design docs, and the most recent commits (`git log --oneline -20`). If a dashboard or project plan exists (e.g. `docs/dashboard.md`), read it. Skim, don't deep-dive — you need shape, not detail.
2. **Generate a wide candidate set, silently.** Brainstorm 8–15 candidate additions internally. Do NOT show this list to the user. Cover different axes: new capability, new UX, new integration, new abstraction, new audience, new business model, new defensive moat, removing something, inverting an assumption.
3. **Score each candidate** on four dimensions:
   - **Smart**: non-obvious, leverages something unique about this project's position.
   - **Radically innovative**: surprises a reader; not a "fast follow."
   - **Accretive**: compounds with what already exists rather than replacing it.
   - **Useful & compelling**: a real user (or self) would be visibly better off; the idea is easy to want.
4. **Pick the single winner.** If two are close, pick the one with the larger blast radius if it works.
5. **Stress-test it.** Spend a moment trying to kill the idea: what's the strongest objection, what would have to be true for it to fail, what's the cheapest experiment that would falsify it. Keep the answers — they go in the output.
6. **Write the output** in the exact format below.

## Output Format

Follow BLUF + Pyramid Principle strictly. Hierarchical numbering on every header. No prose before §1. No preamble like "Here's my analysis." Start at `## 1. Objective`.

```
## 1. Objective

One paragraph. What question we are answering, framed against the current state
of the project. Reference the project by name and what it currently is.

## 2. Recommendation

One sentence — the idea, named. Then 3–5 bullets capturing the essence: what it
is, who it's for, why now, what changes for the user, what the moat is.

## 3. Next Steps

Concrete, ordered. The smallest possible first move that would validate or
falsify the idea. Then the second move. Then the third. Stop at three.

## 4. Why This Idea Wins

### 4.1 Smart
Why it's non-obvious. What insight about the project or its users this rests on
that a casual observer would miss.

### 4.2 Radically Innovative
What it changes about the category, not just the product. What it makes
possible that wasn't possible before.

### 4.3 Accretive
How it compounds with existing surface area. Which existing components become
more valuable because of it. Why this is multiplicative, not additive.

### 4.4 Useful & Compelling
The concrete user (or self) moment that gets visibly better. Tell it as a
micro-scenario — "today X happens; after this, Y happens instead."

## 5. What I Rejected and Why

List 3–5 candidates that were strong contenders. One line each: idea — why it
lost (lower leverage, already partially shipped, off-mission, dependent on
something not yet true, etc.). This proves the recommendation is a choice, not
a default.

## 6. Strongest Objection

State the best argument against the idea. Then answer it honestly — either
refute it, or concede that the idea is conditional on assumption X being true
and name the cheapest way to test X.

## 7. Falsification Plan

The smallest, fastest experiment that would tell you this idea is wrong.
Include: what you'd build (or fake), who you'd show it to, what observable
outcome would kill it.

## Appendix

Any supporting detail that didn't fit above: links to relevant files in the
repo (with paths), data points, prior art. Optional — omit if empty.
```

## Formatting Rules

- **No header is unnumbered.** Every `##` and `###` carries its position number. The reader must be able to write "see §4.3" and have it stay valid.
- **Pyramid Principle**: each section's header summarizes the section below it. Don't bury the lede.
- **No hedging in §2.** The recommendation is one idea, stated decisively. Caveats belong in §6, not §2.
- **No fabrication.** If you don't know enough about the project to justify a claim, say so in §6 as a conditional ("this assumes Y; verify before committing").
- **Length discipline.** §2 fits on one screen. §4 is the longest section. The whole document is readable in under five minutes.
- **One idea only.** If the user pushes back, generate a new single idea — never "options A or B."
