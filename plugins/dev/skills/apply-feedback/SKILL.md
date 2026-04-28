---
name: apply-feedback
description: "Apply tagged review comments (e.g. [MK], [REV]) in the current document immediately, using per-tag interpretation rules from `~/.mstack/dev/feedback-tags.json`. Use when the user says \"apply feedback\", \"apply MK comments\", \"apply review notes\", \"apply my edits\", or wants tagged comments incorporated directly into a document without an approval gate."
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

## Step 2: Apply each comment immediately

For each match, apply the requested change without asking permission, **using the per-tag `action` and `content` fields to inform interpretation**:

- A tag whose `action` says "Apply edits as written; treat as imperative" → just apply the edit.
- A tag whose `action` says "Treat as suggestions; flag for discussion" → in this `apply-feedback` skill, still apply (this skill's posture is apply-now), but be more conservative; if the suggestion is open-ended ("consider rewording"), make the most reasonable edit and note it in your final summary.

Apply edits by:
- Updating content based on the comment
- Removing contradicting information
- Adding missing information
- Restructuring sections if the comment requests it
- **Removing the bracketed tag** (and its inline note) after incorporating the feedback

## Step 3: Preserve flow

Ensure changes integrate smoothly with existing content. Preserve overall structure and tone. Match the document's voice when adding content.

## Important Rules

- Remove ALL configured-tag brackets after incorporating feedback
- Do NOT ask for permission — apply changes directly (this is the apply-immediately skill)
- Be comprehensive — address every comment for every configured tag
- Maintain consistency throughout the document
- Use each tag's `action` and `content` fields as guidance for how aggressively/literally to apply

## Example

With `MK` configured (action: "Apply edits as written"):

**Before:**
```
The system will use the brand_mentions table [MK] Rename to response_metrics.
```

**After:**
```
The system will use the response_metrics table
```

Apply all configured-tag feedback now and update the document.
