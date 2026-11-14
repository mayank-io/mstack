---
name: complete-status
description: Use when the user says "status", "status?", "complete status", "complete-status", "full status", or asks where the project stands, and whenever a session that owns a project reports an event (a landing, a failure, a finished review, a new blocker). Produces the complete status report for the whole project the session owns - milestones, backlog, landing tables, decisions, blockers with time estimates, paused items, next project - re-read from source, never from memory.
---

# Complete Status

Produce the complete status of the **whole project this session owns**. The reader has been away and reads only this message: they must be able to see what is done, what is moving, what is waiting on them and where to click, without asking a follow-up.

**Violating the letter of these rules is violating their spirit.** A status that covers only the last event, answers from memory, or says "unchanged" is not a status.

## When this runs

| Trigger | What to send |
|---|---|
| The user asks: "status", "status?", "complete status", "full status" | The full report, sections 1 to 8 below. |
| Any change the session reports (a landing, a red chain, a review result, a new blocker, a decision made) | The event reply: one-line headline of what changed, then sections 1 to 3 in full (and section 4 if the session lands or tracks landings), any row that waits on the user, then the `Next project:` line. Never the event alone. |

Scope is the project, never the event. A reply about one landing still shows every milestone and the whole backlog.

## Step 1: re-read before answering

Never answer from memory. Before writing a single row:

1. Read the backlog or dashboard file the project keeps, from disk, now.
2. Read the **last result** of every in-flight item: the subagent's final output, the peer session's last message, the chain log, the review verdict. An item is in the state its last result says, not the state it was dispatched in.
3. For a session that lands or tracks landings: read the landing log, and get every SHA from `git rev-parse` / `git log` at this moment, not from an earlier message.
4. Get the local time zone (`date +%Z`) for every time in the report.
5. **Fix disagreements at the source first.** A backlog row whose prose and status disagree (prose says landed, status says in progress) is corrected in the backlog file before the answer goes out. The report then quotes the corrected row.

If a source cannot be read (file missing, peer not answering), the row says so in words. It is never filled in from memory.

## Step 2: write the report in this order

Status comes before decisions: the high-level project table leads, and a D-numbered decision appears only after the results it depends on.

### 1. Headline

One line. For a requested status: where the project stands. For an event reply: what changed.

### 2. Project milestones

- **Completed milestones:** one line each (`✅ M1, <what it delivered>`).
- **In-progress milestone(s):** a detailed table, one row per task: `Item | Owner | State | Notes`.
- **Pending milestones:** one line each (`⏳ M4, <what it will deliver>, <what it waits on>`).

### 3. Backlog

Three parts, each a table:

- **Done:** `Item | State`.
- **In flight:** `Item | Owning session | Stage | State`. Every row names the session that owns it and the stage it is at (plan, plan review round N, implementing, code review, land ready, in chain).
- **Next:** `Item | State`, in the order they will be picked up.

Where the session's scope is the reading platform (PM sessions), reading issues appear only here, in the backlog part. They do not appear in the milestone tables.

### 4. Landings (only for a session that lands, or tracks what lands)

Always the **full** set, every time. Never a delta, never "unchanged", never "same as before". All four parts are tables, never prose. Times in the user's local zone, with the zone named in the column header.

- **4.1 Reached main, in time order.** ONE table of everything that reached main: each chain with `Start | End | Duration | Result (✅ or ❌) | Pushed SHAs`, and chain-free or direct docs landings interspersed at the time they landed.
- **4.2 Chain in flight.** `Chain | Start | Running for | Current step`.
- **4.3 Queue.** In order: `# | Item | State`.
- **4.4 Not ready yet.** `Item | Why not`.
- **4.5 Mains.** `Repo | main SHA`, one row per repo.

A part with nothing in it keeps its header and a single row saying `none`.

### 5. Decisions waiting on the user

One table, placed after the results the decisions depend on. `Decision | State | Open this`. The Decision cell is the id plus what is being decided: "D83, how to run the 11 exit readings", never "D83".

### 6. Blockers

`Blocker | State | Time remaining (est.) | Hinges on`, then a **Total** row. Every figure is an estimate and is labelled as one. Say what each hinges on, and build it from observed pace, not hope: the number of plan review rounds still to run, about 35 minutes per landing chain, about 10 minutes per regeneration, unless this project has measured a different pace, in which case use that and say so.

### 7. Paused on the user's word

Items the user has paused that are not in the current stream, in one row or one paragraph, each with `⏸`. They are listed every time so nothing drops out of view.

### 8. Next project

The last line of every report and every event reply, exactly one line: `Next project: <what the session picks up next>`.

## Row rules (every table)

1. **The State cell starts with exactly one glyph, then words.**

   | Glyph | Meaning |
   |---|---|
   | ✅ | landed / done |
   | 🔄 | in progress |
   | ⏳ | queued, or waiting on another item |
   | ⛔ | waiting on the user |
   | ⏸ | paused |
   | ❌ | failed / red |

2. **Never the word "green".** Say what happened: "landed", "passed", "tests pass", "clean".
3. **Full task names, never bare ids.** The Item cell says what the task does in plain words, with the id in brackets after: "Regenerate the exit readings with the new scorer (B41)". The same for decisions, milestones, chains and issues.
4. **Every row that waits on the user (⛔) names what to open, in the row.** The file to review as a full absolute path, and the same for any URL, doc or page the user must open. "See the plan" is not a path.
5. **Times carry a zone.** Local zone of the user, named.

## Before sending: check

- Every source was read in this turn; no row comes from memory.
- Every milestone of the project appears: completed, in progress, pending.
- Backlog has all three parts; every in-flight row has an owning session and a stage.
- Every State cell starts with one of the six glyphs. The word "green" appears nowhere.
- No bare id anywhere, in a table or in prose.
- Every ⛔ row carries a full path or URL.
- Landing parts (if this session lands or tracks landings) are complete tables, with SHAs read just now.
- Every blocker has an estimate labelled as an estimate, what it hinges on, and there is a total.
- Paused-on-the-user's-word items are listed.
- The last line is `Next project: …`.

## Red flags: stop, this is not a complete status

- "Only one thing changed, I'll report that" → the event reply still carries the whole project table.
- "The landing table is unchanged since last time" → print it in full anyway.
- "I remember where that agent got to" → read its last result.
- "The backlog row is stale but I know the truth" → fix the row, then report.
- "The user knows what D83 is" → write what it decides.
- "The file is in the usual place" → write the full path in the row.
- "It should take about an hour" → label it an estimate and say what it hinges on.

## Worked example

`example.md` in this skill's directory shows a full report and an event reply for the same project. Match its shape, not its content.
