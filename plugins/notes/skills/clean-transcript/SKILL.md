---
name: clean-transcript
description: "Turn a raw transcript into readable verbatim Markdown — strip timestamps, merge fragmented lines, insert paragraph breaks and chapter headings. Use when the user says \"clean this transcript\", \"format this transcript\", or after fetch:youtube-transcript hands back raw timestamped text. Guarantees the output is word-for-word identical to the input."
---

# Clean Transcript

Raw transcripts arrive as timestamped fragments — auto-captions split sentences across timed segments and sprinkle `[Music]` markers through them. This skill merges them into readable prose **without changing a single word.**

## Run the script. Do not clean by hand.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/clean-transcript/scripts/clean.py" \
  RAW.txt OUT.md [META.json] [--speakers "David Puell,Yassine Elmandjra"]
```

| Argument | Meaning |
|---|---|
| `RAW.txt` | raw transcript text — the `transcript` field from `fetch:youtube-transcript`, written to a file |
| `OUT.md` | where the cleaned Markdown goes |
| `META.json` *(optional)* | JSON with a `chapters` array; each entry needs `start_time` (or `seconds`) and `title` |
| `--speakers` *(optional)* | comma-separated names whose **already-present** labels get bolded |

It prints `segments:`, `chapters inserted:`, `chars out:` and any corruption warnings to stderr, then `OUTPUT_FILE:<path>` as the final stdout line. Chain on that line.

**Why a script and not instructions:** verbatim is a property you can either guarantee or merely request. This script only deletes timestamps and noise markers and inserts whitespace, headings and bold markers — so the output is provably the input's token stream minus deliberate deletions, and `tests/test_clean.py::test_verbatim_invariant` checks exactly that over a 50k-character fixture. An LLM asked to "clean but stay verbatim" silently fixes grammar, drops filler, and tightens sentences. That has produced bad captures before.

## What it does and does not do

**Deletes:** leading timestamps (`mm:ss` and `hh:mm:ss`), and the noise markers `[Music]` `[Applause]` `[Laughter]` `[Snorts]` `[Inaudible]` `[Silence]` `[Crosstalk]` `[Side conversation]`, case-insensitively.

**Inserts:** paragraph breaks (at ≥700 characters *and* a sentence terminator — both required, so a long unpunctuated run stays whole rather than being cut mid-sentence), `## Chapter Title` headings, and `**Name:**` bolding for labels already in the text.

**Never:** rephrases, fixes grammar, adds or removes punctuation, drops filler words (`um`, `like`, `you know`, `ठीक है`), invents a speaker label, translates, or summarises. A 90-minute video yields a proportionally long transcript.

## Corruption scan

`caption_warnings` from `fetch:youtube-transcript` detects figures the caption **omitted**. It cannot see one it **mangled** — `$und00` where the speaker said `$1,050`, or `a,50` for `1,050`. This script scans the cleaned text for those signatures and reports them on stderr:

- a currency symbol not followed by a digit
- letters immediately before a comma-number, or digits immediately before comma-letters
- `%` whose nearest preceding non-space character is not a digit

**Any flagged figure that a summary will quote — a price target, a threshold, a headline number — must be re-transcribed from audio before you trust it.** Use the caption-verification procedure in `fetch:youtube-transcript`. A mangled figure reads as authoritative, which is what makes it dangerous: one such corruption (`a,50` for `$1,050`) once carried an entire gold price target.

The scan is heuristic. It flags candidates; it does not prove corruption, and it will not catch every case.

## Non-English transcripts

Clean in the original language. **Do not translate** unless the user asks. If they do, put the translation below a `---` separator with the same chapter structure — never in place of the original.

## Tests

```bash
uv run --group dev pytest plugins/notes/skills/clean-transcript/tests/ -v
```

29 tests. If you change `clean.py`, mutation-test the change: break the behaviour deliberately and confirm a test fails. A suite that has never failed proves nothing — the noise-only-segment guard was already once covered by an assertion too lenient to catch its removal.
