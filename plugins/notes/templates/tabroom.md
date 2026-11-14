# Tabroom Template

Output shape for a note captured from a Tabroom competitor history page (`tabroom.com/user/student/history.mhtml`): one tournament's judges' scores and feedback. Selected by `notes:clip`.

## Scope

Output shape and declarative settings only. Never sequences tool calls.

## Frontmatter

```yaml
---
tags:
  - clippings
  - tabroom
  - speech-and-debate
  - inbox
source: {{source}}
student: "{{student}}"
tournament: "{{tournament}}"
tournament_url: {{tournament_url}}
event: "{{entries[].event}}"
date: {{tournament_start}}
date_end: {{tournament_end}}
location: "{{location}}"
rounds: {{rounds_count}}
ballots: {{ballots_count}}
date_captured: {{today}}
---
```

- **`date` is the tournament's first day**, from `tournament_start`. Leave it empty when the fetcher returned `null`; never infer it from the capture date.
- **`event` is a list** when the student entered more than one event.
- **Do not copy `account` into the note.** It is the login the page was read through, kept in `results.json` to prove which account was used; it is a credential identifier, not content.

## Body

```markdown
# {{student}}: {{tournament}}

> {{event}} · {{location}} · [[{{tournament_start}}]] to [[{{tournament_end}}]]
> Captured [[{{today}}]] from [Tabroom]({{source}})

## Summary

[2 to 4 sentences: how far the entry went, the range of ranks, and the points the judges agree on. Paraphrase; no evaluation of the judges.]

## Results

{{the Results table from results.md, one row per ballot, unchanged}}

## Feedback

{{the Feedback section of results.md, unchanged: a heading per round, a heading per judge, every comment box}}

# Analysis

## What the judges agree on

- [a point raised by two or more judges, with the judges named]

## One judge only

- [a point only one judge raised, with the judge named]

## To work on next

- [concrete, drawn from the feedback above; nothing the judges did not say]

## Related
```

## Rules

- **The feedback is the source and goes in verbatim.** Every judge, every comment box, every line, in the judge's spelling and capitalisation. Do not correct typos, merge two judges' comments, or drop a ballot because it is short. `results.md` already carries it in order; copy it rather than retyping it.
- **Heading levels.** The title is the note's only `#` above the source. In `results.md` a round is `####` and a judge is `#####`; under `## Feedback` they become `###` and `####`. With two events, keep the event as `###` and leave rounds and judges at `####` and `#####`.
- **Keep the scores beside the judge's name** in the judge heading (`Okafor, Ngozi (Rank 2)`), so a ballot read on its own still says how it scored.
- **A ballot with no written feedback stays in the Results table**, and the Feedback section says it has none. Leaving the judge out makes a missing comment look like a missing judge.
- **`# Analysis` comes after the source**, as an `h1`, so the boundary between the judges' words and yours is visible in the outline. Attribute every point to the judge who made it.
- **Filename:** `{{student}} - {{tournament}} - {{event}}.md`, with the event's parenthetical code dropped (`Informative Speaking`, not `Informative Speaking (INF)`).
- Say plainly what could not be captured, and distinguish *"the page had no feedback for this ballot"* from *"the wrong account was signed in"*: the first is final, the second is fixed by switching browsers.
