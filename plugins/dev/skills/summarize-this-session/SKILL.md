---
name: summarize-this-session
description: "Summarize the current conversation: ongoing task progress + continuous improvement insights. Use when the user says \"summarize this\", \"recap\", \"summary\", \"wrap up\", or wants a checkpoint of work-in-progress and lessons learned."
---

# Summarize Current Conversation

Review everything that has happened in this conversation and produce a two-section summary.

## Instructions

Look back through the entire conversation history — every user message, every tool call, every result, every correction.

Produce the following two sections:

---

## Ongoing Task

Summarize the work in progress:

- **Initial Request**: What the user originally asked for. State it clearly and concisely.
- **Progress Made**: What has been accomplished so far. List concrete deliverables (files created, bugs fixed, features implemented, decisions made). Be specific — reference file paths, function names, and outcomes.
- **Next Steps**: What remains to be done. If the task is complete, say so. If there are open questions or follow-ups, list them.

## Continuous Improvement

Analyze the conversation for learning opportunities:

- **Mistakes Made by Claude**: Actions Claude took that were wrong, suboptimal, or had to be redone. Include:
  - What happened
  - What the correct approach was
  - Why Claude got it wrong (wrong assumption, missing context, tool misuse, etc.)

- **Mistakes Pointed Out by Human**: Corrections the user explicitly made. Include:
  - What the user corrected
  - What Claude was doing wrong
  - Whether this is a recurring pattern

- **Lessons Learned**: Actionable takeaways from this conversation that would improve future sessions. These could be:
  - Workflow improvements
  - Tool usage patterns
  - Project-specific conventions discovered
  - Things that should be added to CLAUDE.md or memory
  - Skills or plugins that would have helped

---

## Formatting Rules

- Be honest and specific — don't gloss over mistakes or be vague
- If there were no mistakes in a category, say "None" — don't fabricate issues
- Keep each bullet concise but include enough detail to be actionable
- Reference specific messages or tool calls when describing mistakes
