# think — parallel divergent ideation

> **An architectural fix for premature convergence in autoregressive reasoning.**

This plugin packages the **ADHD** skill — parallel divergent ideation for coding
agents — as an mstack plugin. It spawns N isolated reasoning branches under
deliberately distorted cognitive frames (with zero shared context during
divergence), then runs a separate critic pass to score, cluster, prune traps,
and deepen the survivors.

---

## Source & credit

This is a **vendored copy** of the ADHD skill. All design credit goes to the
original author. Nothing here is my own work beyond the mstack packaging.

| | |
|---|---|
| **Author** | Udit Akhouri — [@akhouriudit](https://x.com/akhouriudit) · [LinkedIn](https://www.linkedin.com/in/udit-akhouri-10160a168/) · researchudit@gmail.com |
| **Source repo** | <https://github.com/UditAkhourii/adhd> |
| **Preprint** | *ADHD: Parallel Divergent Ideation for Coding Agents* — <https://adhdstack.github.io/> |
| **License** | MIT (preserved verbatim in [`LICENSE`](./LICENSE)) |
| **npm package** | [`adhd-agent`](https://www.npmjs.com/package/adhd-agent) (the upstream Node/TS library + CLI) |

The skill body lives at [`skills/adhd/SKILL.md`](./skills/adhd/SKILL.md), vendored
verbatim. The original divergent-ideation prose spec it operationalizes is
preserved at [`SOURCE-SPEC.md`](./SOURCE-SPEC.md). Only this README has been
adapted from the upstream README to fit the mstack plugin context.

---

## Why it exists

Linear Chain-of-Thought gets trapped in local minima: each generated token
conditions the next, so the model anchors on whatever it said first.
Tree-of-Thought widens the search but still walks a single shared context, so
anchoring persists across branches. **ADHD treats this as an architectural
problem, not a prompting one** — N isolated reasoning processes under distorted
cognitive frames, zero shared context during divergence, then a separate critic
pass.

> The first three answers the model would give are the answers a senior engineer
> would give in thirty seconds. Correct. Forgettable. The interesting answers
> live past number three, in the awkward middle nobody walks into.

## Usage

```
/think:adhd "design a rate limiter that survives a leader election"
/think:adhd "name this function"
/think:adhd "our CLI hangs for 90s on LLM calls — what's the right retry/UX?"
```

The skill also **auto-triggers** on brainstorm / ideate / design / naming /
"give me a few ways to…" intents, and self-judges before firing on anything that
isn't an explicit `/think:adhd` invocation (it aborts on lookups, syntax help,
known-root-cause bugs, and closed phrasing like "quick" / "standard" /
"textbook"). The explicit command skips that gate and runs the full loop.

## How it works — two phases, hard wall between them

### Phase 1 — Diverge (no critic)
Pick 5 cognitive frames. Spawn 5 **parallel, isolated** Agent/Task calls — one
per frame. Each branch sees only the problem, any context, its frame's vantage
prompt, and an instruction that **forbids evaluation, ranking, or hedging**.
Branches never see each other, so anchoring is eliminated by construction.

### Phase 2 — Focus (critic on)
1. **Score** every idea on `novelty / viability / fit` (0–10); tag traps with a
   one-line mechanistic reason.
2. **Cluster** by underlying angle, not surface keyword — surfaces the *shape*
   of the design space.
3. **Deepen** the top 3 non-trap ideas: sketch, load-bearing risk, first concrete
   step, and 3–5 child ideas.

Output: the wide clustered set, a 2–4 idea shortlist, the non-obvious-but-viable
pick flagged with ★, the trap list with reasons, the deepened branches, and one
provocation.

## Frames (the cognitive distortions)

15 built-in frames, biased toward engineering on code-shaped problems. A sample:
hardware engineer, regulator/auditor, 10-year-old, competitor-trying-to-break-it,
biology, logistics, game design, markets, inversion, $0-budget / infinite-budget,
remove-the-load-bearing-assumption, speedrunner, ant colony, 3am-on-call. Each is
a vantage prompt + tags; the full table is in [`SKILL.md`](./skills/adhd/SKILL.md).

## When to use it (and when not)

**Use it for:** architecture & design decisions, API/SDK/CLI surface design, fuzzy
debugging (generate hypothesis *classes*), migration/refactor planning, naming,
code-review widening, strategy/positioning — anywhere you'd say *"give me a few
ways to…"*.

**Don't use it for:** lookups, known-root-cause bugfixes, anything one search away,
inner-loop / per-keystroke work, single-correct-answer problems.

> One-sentence test: *if a junior would Google it and find the answer, a single-shot
> answer wins. If a senior would say "hm, let me think about this differently for a
> minute" — that's the moment to reach for `/think:adhd`.*

## Cost

5 diverge + 1 score + 1 cluster + 3 deepen ≈ **10 LLM/Agent calls per run**,
roughly 5–10× a single-shot answer, 30–90s wall clock. Frame it as *$0.30 to widen
a $50k architecture decision* — run it at decision points, not on every keystroke.

## Evals

The upstream repo ships a reproducible eval suite (LLM-as-judge, skeptical
staff-engineer posture) comparing ADHD head-to-head against a single-shot baseline
across open-ended engineering problems. Headline result: ADHD wins 5 of 6 problems,
with the largest gap in **trap detection** (~5×). Full methodology and per-problem
verdicts live in the source repo.
