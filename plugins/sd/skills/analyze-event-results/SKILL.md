---
name: analyze-event-results
description: "Use when the user shares a tabroom.com tournament link (a results page or any tab: Invite, Entries, Judges, Pairings, Live Updates, Results) or names a tournament, and asks about a whole speech event's results: \"why didn't X break\", \"how close was X to finals\", \"who made the break\", \"analyze the results of this event\", \"download all the results\". Not for one competitor's own ballots and judge comments (fetch:tabroom-results)."
---

# Analyze Event Results

One script downloads a Tabroom tournament's public data and writes one speech event's ballots, standings and a break analysis to a directory. **Run it; do not open the result pages, parse them, or rank entries by hand.** Its totals and seeds are checked against Tabroom's own, and a hand-built ranking has no such check.

The data comes from Tabroom's documented backup endpoint, `/api/download_data.mhtml?tourn_id=<n>`: one plain GET, no login, the whole tournament as JSON. Never crawl the result pages instead; they need a login and Tabroom asks automated readers to stay off them.

## Input

`$ARGUMENTS`:

- **The tournament** (required), as either:
  - any Tabroom URL that carries `tourn_id`: a round's results, Final Places, Prelim Seeds, or the Invite, Entries, Judges, Pairings, Live Updates or Results tab;
  - the tournament's name. The script looks it up with Tabroom's search. An exact name that repeats every year resolves to the latest one that has started; a loose name with several matches fails and lists them.
- **The event** (`--event`): its name or abbreviation ("Novice Oratory", `NOO`).
- **A competitor** (`--competitor`, optional): the entry the user is asking about. Part of the name is enough.
- **An output directory** (optional): omitted, a temp directory is used.

`--event` can be left out when something else names the event: a `round_id` or `event_id` in the link, a `--competitor` who is in exactly one speech event, or a `result_id` link (Final Places, Prelim Seeds). For a `result_id` link the script reads the event's abbreviation off that page through the gstack browser, because the JSON carries no result ids; when the browser is not available or not signed in to Tabroom, it fails and lists the events.

When nothing names the event and the user did not say, run once without `--event`: the error lists the tournament's speech events. Ask the user which, or pick it when their words make it plain.

If the question is about a person ("why didn't she break") and no name is given, ask for the name before running.

## Run

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tabroom_event_results.py" "<url or tournament name>" [out_dir] [--event "<name>"] [--competitor "<name>"]
```

Run it through the Bash tool **outside the sandbox**: it needs the network, and for a `result_id` link the gstack browser. Run it from the user's working directory, not from the plugin's.

To re-run on an earlier download (another event or competitor, no network):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/tabroom_event_results.py" --from-raw "<earlier out_dir>" [out_dir] --event "<name>" [--competitor "<name>"]
```

**Output contract:** the final stdout line is `OUTPUT_DIR:<abs path>`. No marker means failure; stop and report the `ERROR:` line. One case writes the data and still fails: a `--competitor` that matches no entry, or several. The error lists the matches; re-run with `--from-raw` and a name from `standings.csv`.

## What it writes

| File | Contents |
|---|---|
| `analysis.md` | Numbered sections: objective, key findings, how the break worked, the competitor's rooms, what one rank better would have changed, who broke, judge point scales, data and checks |
| `standings.csv` | One row per entry in prelim seed order: ranks and points by round, rank total, reciprocals, points, 1sts, whether they broke, elimination ranks, final place, Tabroom's own seed |
| `ballots.csv`, `ballots.json` | One row per ballot: round, stage, section, room, speaking order, entry, code, name, school, judge, rank, points |
| `event.json` | Tournament, dates in its own timezone, event, rounds, tiebreakers as Tabroom names them, break size, the check result, `captured_utc` |
| `result_sets.json` | Tabroom's own result sets for the event (Final Places, Prelim Seeds) |
| `raw/tournament_<id>.json` | The whole tournament as served, every event included |

## Report

Answer the user's question from `analysis.md`, leading with its Key findings. State, in this order:

1. Where the competitor seeded, the size of the break, and who held the last place in.
2. Which tiebreaker separated them from the cut, with both values. For a competitor who broke: their seed and final place.
3. Which single rank, one place better, would have been enough, from the "one rank better" table.
4. What the data cannot show: ballot comments are visible only to the competitor's own login (`fetch:tabroom-results` reads them).

Then give the output directory. When the user wants the analysis kept, hand `analysis.md` and the directory to their note-writing skill; this skill writes no notes.

## Read the warnings before reporting

Each stderr `WARNING:` changes what can be claimed:

| Warning | What to say |
|---|---|
| `prelim tiebreakers not read from Tabroom's result sets` | The seeding order (ranks, reciprocals, points) is assumed, not read from the tournament |
| `rebuilt total(s) differ from Tabroom's` | Report the mismatches in "Data and checks" before any conclusion; the seeding may be wrong |
| `rebuilt seed(s) differ from Tabroom's Prelim Seeds` | Tabroom's seed order is the authority; report the differences and do not explain the cut by the rebuilt order |
| `rebuilt totals were not checked` | No result set with prelim totals is published; the seeding is unverified |
| `entries that broke are not the top seeds` | The tournament broke on something else; do not explain the cut by these tiebreakers |
| `no scored ballots for: <round>` | That round is unpublished or empty; name it |

"Data and checks" in `analysis.md` also says when points were read from result-set strings instead of ballots, and when some ballots carry no points at all.

## Limits

- **Speech events with ranks and points.** A debate, congress or worlds event is refused: those are decided on wins and losses.
- **"Broke" means "has a ballot in the first elimination round."** With no elimination round scored, there is no break to read.
- **The one-rank-better table swaps two ranks in one room and keeps the judges' points.** It shows what the arithmetic needed, not what a judge would have done.
- **Entries level on every tiebreaker** are listed alphabetically; the analysis names them.
- **Public data only.** A tournament that hides its results returns none, and the script says so.
- The data holds students' names. Keep the output where the user asked for it and send none of it to outside services.

## Tests

```bash
uv run --group dev pytest plugins/sd/scripts/tests/ -v
```
