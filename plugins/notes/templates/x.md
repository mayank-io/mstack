# X / Twitter Template

Output shape for a note captured from `x.com` or `twitter.com`. Selected by `notes:clip`.

## Scope

Output shape and declarative settings only. Never sequences tool calls — fetching, cleaning and writing belong to `notes:clip`, `fetch:x-post` and `notes:create`.

## Frontmatter

```yaml
---
tags:
  - clippings
  - x-post
  - inbox
source: {{url}}
author: "@{{handle}}"
author_name: {{display_name}}
date: {{post_date}}
date_captured: {{today}}
likes: {{likes}}
reposts: {{reposts}}
views: {{views}}
---
```

Add `x-thread` to `tags` for a multi-post thread, `x-article` for long-form. Omit a metric entirely rather than writing `0` when it could not be read — a real zero and an unread value are different facts.

### Video posts

`fetch:x-post` writes `media_type`, `video_duration`, `video_seconds` and `transcript: pending`. Replace `pending` once the transcript is in the note, and add the attestation keys:

```yaml
media_type: video
video_duration: {{h:mm:ss}}
video_seconds: {{n}}
transcript: full
transcript_method: {{backend}}/{{model}}        # e.g. mlx-whisper/large-v3-turbo
transcript_words: {{n}}
reading_status: to-read
read_context: inflight | desk
read_minutes: {{n}}
```

`read_context: inflight` is a promise the note reads with **no network**, which a video post can only keep if the full transcript is archived in it.

A re-upload carries two more, because X shows the poster and not the author:

```yaml
content_author: "@{{original handle}}"
original_post: {{original status url}}
```

## Body — order

**Fixed, and not a stylistic preference:** summary, then the source verbatim, then your analysis. `notes:clip` Step 2.6 has the reasoning — the source is the part that cannot be regenerated once the post is gone, and analysis placed above it lets a thin capture read as a thorough one.

```markdown
# {{handle}}: {{title}}

> **@{{handle}}** · {{likes}} likes · {{reposts}} reposts · {{views}} views
> Posted [[{{post_date}}]] · captured [[{{today}}]]

## Summary

[What the post says, in your paraphrase. Key claims, figures, and takeaways.
This is the source's content restated — not your evaluation of it.]

## Post

[the source, verbatim — see below]

# Transcript          ← video posts only

# Analysis
```

**Keep your own voice out of everything above `# Analysis`.** The summary paraphrases; it does not judge. Verification, doubts and scoring go below.

## Body — single post

Post text verbatim, preserving line breaks. Then embedded images, then:

```markdown
---

**Engagement:** {{likes}} likes · {{reposts}} reposts · {{views}} views
**Posted:** [[{{post_date}}]]
```

## Body — thread

```markdown
# {{title derived from the first post}}

## 1. {{short summary of post 1}}

{{post 1 text}}

![{{descriptive-name}}](attachments/{{filename}}.jpg)

---

## 2. {{short summary of post 2}}
```

Number every post. **Start from the thread root, not the shared link** — `fetch:x-post` walks backward to find it, and the note must begin where the thread does.

## Body — X Article

Add `x-article` to `tags`. An Article is a full essay, not a post — one ran to 44,000 characters across 28 sections.

```markdown
# {{article_title}}

![{{article_title}}](attachments/{{filename}}.jpg)

{{intro — the text before the first heading, including the subtitle line}}

## {{h1 heading}}

{{section text}}

### {{h2 heading}}

{{section text}}
```

- **`h1` → `##`, `h2` → `###`.** The document title is the note's only `#`.
- **Keep the intro.** The text before the first heading carries the subtitle and thesis; it is not preamble to drop.
- **Never emit a heading twice.** `fetch:x-post` returns the body as one block *with the headings already inside it*, plus a separate heading list for splitting. Concatenating the list onto the body duplicates all of them.
- **Sections in document order**, never sorted or grouped.

### Reference list

A well-sourced Article can carry 50+ external links. When there are more than ~10, add a section after the body summarising them by domain — the citation profile is often the most reusable part of the note:

```markdown
## Sources

{{n}} external references: {{count}} {{domain}} · {{count}} {{domain}} · …
```

## Body — video post

**A video post whose note contains only the caption is not a clip.** The caption is the hook; the video is the content. `fetch:x-post` Step 1.5 transcribes it.

**A note without the `# Transcript` section populated is not an X clip.** If the transcript could not be obtained, say so under that heading and name the reason, rather than letting the summary stand in for it.

```markdown
## Post

{{caption verbatim}}

---

# Transcript

*{{duration}} · transcribed with {{backend}} {{model}} · {{n}} segments · {{n}} words · cleaned by `notes:clean-transcript`, word-for-word identical to the raw transcript.*

{{cleaned prose — paragraphs, no timestamps}}
```

`notes:clean-transcript` **strips the timestamps**; its guarantee is that the surviving token stream is the raw one unchanged. Record the tokens-in/tokens-out check in the attestation if it is worth proving.

The attestation line is not decoration. It is what lets a later reader tell a `large-v3-turbo` transcript from a `tiny` one, and it must name any departure from a single straight run — a re-transcribed window, a spliced boundary, a backend switched mid-way.

**Check for a decoder repetition loop before the transcript goes in.** Whisper can catch a phrase and emit it for the rest of the file; the result still runs the full duration and still reads as English, so length and coverage checks both pass while the content is gone. `whisper_transcriber.py` warns on stderr and records `repetition_warnings` in its JSON — that list must be empty.

## Required sections

Both at the end, in this order, and **below** the transcript on a video post:

```markdown
# Analysis

*Everything below this line is mine, not the source's.*

- 2–4 bullets: the key claim, what is notable, what is unsupported.

## Verification

[Claims recomputed from source data. State what replicated and what did not.]

## Related

- [[$TICKER]] for each ticker mentioned
- [[@Person]] for each person with a note
```

`# Analysis` replaces the older `## Initial Take`. It is an `h1` because it is a peer of `# Transcript`, not a subsection of the source — the heading level is what makes the boundary between the source and your voice visible in the outline.

## Rules

- **Images at original resolution.** `fetch:x-post` requests `name=orig`; embed those. A downscaled chart is unreadable at the point it matters.
- **Tickers as wikilinks** — `[[$AAPL]]`, never bare `$AAPL`. `notes:create` applies the vault's convention; do not fight it.
- **Filename:** `@{{handle}} - {{short description}}.md`. Never include the status ID.
- **Credit the author, not the poster.** X shows who posted. A natively re-uploaded video is attributed to the re-uploader by the page itself and by every metric on it; only `yt-dlp -J` (an `id` that differs from the status id, a `t.co` resolving to another account's status of identical duration) exposes the original. Record both: `author` is who posted, `content_author` is whose work it is.
- **Quote what was said, flag what was not.** If replies ask something the author never answered, record that as a gap in the source rather than inferring an answer.
