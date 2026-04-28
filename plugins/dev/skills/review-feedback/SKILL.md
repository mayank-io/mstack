---
name: review-feedback
description: "Review tagged comments (e.g. [MK], [REV]) in the current document, present a plan, and apply after approval. Uses per-tag interpretation rules from `~/.mstack/dev/feedback-tags.json`. Use when the user says \"review feedback\", \"review MK comments\", \"plan the feedback\", or wants a plan-then-apply flow for tagged review notes in a document."
---

You are reviewing a document that contains feedback comments tagged with one or more configured prefixes (e.g., `[MK]`, `[REV]`). Tags and their interpretation rules are configured per-user in `~/.mstack/dev/feedback-tags.json`.

## Step 0: Load feedback tag configuration

Run this bash to check for the config file:

```bash
mkdir -p ~/.mstack/dev
CONFIG=~/.mstack/dev/feedback-tags.json
if [ -f "$CONFIG" ] && [ -s "$CONFIG" ]; then
  cat "$CONFIG"
else
  echo "MISSING"
fi
```

### If output is `MISSING` (first run)

1. Create the file with the default `MK` entry. Use the Write tool to write `~/.mstack/dev/feedback-tags.json` with this content:

   ```json
   {
     "tags": [
       {
         "tag": "MK",
         "from": "Document author (initials = MK for Mayank)",
         "content": "Direct edit instructions, factual corrections, rephrasing requests, structural changes",
         "action": "Apply edits as written; treat as imperative; only push back if ambiguous"
       }
     ]
   }
   ```

2. Tell the user verbatim:

   > Saved your feedback tag config to `~/.mstack/dev/feedback-tags.json`. Pre-seeded with `MK` as the default. **Edit this file directly to add, modify, or delete tags later.**

3. Use AskUserQuestion: "Want to add another tag now? You can also add more later by editing the file." with options:
   - A) No, continue with MK
   - B) Yes, add another tag

4. **If the user picks B**, ask 4 questions in sequence (one AskUserQuestion call each, free-text answers):
   - "What tag prefix? (short uppercase letters only — e.g., REV, FB, TODO. Will be matched case-insensitively in documents.)"
   - "Who are these comments from? (e.g., 'External reviewer')"
   - "What do these comments typically contain? (e.g., 'Suggestions and open questions')"
   - "What action should I take with these comments? (e.g., 'Treat as suggestions; flag for discussion before applying')"

   Read the current config, append the new tag object to the `tags` array, write the updated file. Then ask "Add another?" again — loop until user says no.

5. Proceed to Step 1 once setup completes.

### If output is valid JSON

Parse it. Build a list of all configured tags from the `tags` array. Each tag has fields `tag`, `from`, `content`, `action`.

If JSON is malformed, warn the user (e.g., "feedback-tags.json is invalid JSON, falling back to default MK tag for this run"), then use the default `MK` tag with the same defaults as the first-run pre-seed.

## Step 1: Locate all configured tag comments in the document

For each tag from the loaded config, search the document case-insensitively for the bracketed pattern. For example, if tags `MK` and `REV` are configured, search for `[MK]`, `[mk]`, `[Mk]`, `[REV]`, `[rev]`, `[Rev]`, etc.

Use the Grep tool with the `-i` flag, or `grep -i "\[mk\]"` style commands. Aggregate matches across all configured tags.

If no matches found for any tag, tell the user: "No comments found for any configured tag: TAG1, TAG2, …" listing the configured tag prefixes, and stop.

## Step 2: Build the plan

For each match, draft the proposed change. Use the per-tag `from`, `content`, and `action` fields to shape the proposal:

- For tags with `action` like "Apply edits as written" → propose the literal edit, framed as "applying as instructed."
- For tags with `action` like "Treat as suggestions; flag for discussion" → propose options, alternatives, or open the comment as a question for the user.

## Plan Format

Group comments by tag. Present like this:

```
## Feedback Review Plan

### Tag `[MK]` (from: Document author — apply as written)

#### Comment 1 (Line X): [MK comment text]
**Proposed Change**:

[Show the ACTUAL content that will be added/changed, not a description]
[Include full sections, code blocks, paragraphs - everything that will change]
[If adding a new section, show the complete section text]
[If modifying text, show the full before/after]

**Impact**: [How this affects other sections]

---

### Tag `[REV]` (from: External reviewer — flag for discussion)

#### Comment 1 (Line Y): [REV comment text]
**Proposed Change**:

[For suggestion-style tags, show the proposal AND any alternatives]

**Impact**: [How this affects other sections]
**Note**: [Any clarifying question raised by the suggestion]

[... continue for all tags and comments ...]

## Summary of Changes
- [List all major changes, grouped by tag if helpful]

## Questions for Clarification
- [Any ambiguous feedback that needs clarification]

Please review and approve, or provide additional guidance.
```

**IMPORTANT**: Under "Proposed Change", always show the complete, actual content that will be added or modified. Do not just describe what will be changed — show the exact text, code, sections, or paragraphs that will appear in the document.

## Step 3: Wait for approval

Present the plan and stop. Do not apply changes until the user approves.

## Step 4: Apply on approval

Once approved, apply all proposed changes:
- Update content per the plan
- Remove the bracketed tag (and its inline note) for every comment incorporated
- Maintain consistency throughout

## Important Rules

- **Present plan BEFORE making changes** — wait for user approval
- **Be comprehensive** — address every comment for every configured tag
- **Ask clarifying questions** — if feedback is unclear, raise it in the plan
- **Show impact** — explain how each change affects the document
- **After approval**:
  - Remove all configured-tag brackets
  - Apply all approved changes
  - Maintain consistency throughout

Review the document and present your plan now.
