---
name: surface-usage-patterns
description: "Surface recurring patterns from Claude Code sessions and propose skills, plugins, agents, and CLAUDE.md improvements. Use when the user says \"surface usage patterns\", \"analyze my usage\", \"audit my sessions\", \"find improvement opportunities\", or wants to know what's worth automating from their recent work."
---

# Surface Usage Patterns

Analyze all Claude Code sessions on this computer to identify usage patterns and improvement opportunities.

## Step 1: Gather Session Data

Scan all Claude Code session data. Sessions are stored in `~/.claude/projects/` as JSONL files.

```bash
# Find all session directories and conversation files
find ~/.claude/projects -name "*.jsonl" -type f 2>/dev/null | head -100
```

Also check for:
- `~/.claude/` for any global configuration and history
- Project-level `.claude/` directories for project-specific patterns

Read a representative sample of recent sessions (at least 10-20) to understand what the user does across projects.

## Step 2: Analyze Usage Patterns

For each session, extract:
- **What task was performed** (bug fix, feature, refactor, research, DevOps, etc.)
- **Which tools were used most** (Bash, Read, Edit, Write, Agent, WebSearch, etc.)
- **Which skills/commands were invoked** (`/commit`, `/review-pr`, custom skills, etc.)
- **Repetitive multi-step workflows** (sequences of actions that recur across sessions)
- **Common pain points** (retries, corrections, clarifications that suggest friction)
- **Projects worked on** and their domains

## Step 3: Produce the Report

Present a structured breakdown with the following sections:

### Most Frequent Activities
Rank the top activities by frequency. Include:
- Category (e.g., "Code review", "Feature implementation", "Debugging")
- Approximate frequency (daily, weekly, occasional)
- Typical workflow steps involved

### Candidates for Skills
Identify workflows that should become reusable skills. A good skill candidate:
- Is a multi-step workflow that repeats across sessions or projects
- Has a consistent pattern but isn't currently codified
- Would benefit from documented best practices and guardrails

For each candidate, provide:
- **Name**: Suggested skill name (kebab-case)
- **Trigger**: When this skill should activate
- **Current workflow**: What the user does today (steps)
- **Improvement**: What the skill would standardize or automate

### Candidates for Plugins
Identify tool integrations or capabilities that should become standalone plugins. A good plugin candidate:
- Wraps an external service or API
- Has multiple related commands
- Could benefit from hooks or agents
- Is reusable across projects

For each candidate, provide:
- **Name**: Suggested plugin name
- **Commands**: What commands it would expose
- **Why standalone**: Why this deserves its own plugin vs. being a skill

### Candidates for Agents
Identify tasks that should become autonomous subagents. A good agent candidate:
- Requires deep context or multi-file analysis
- Can run independently without user interaction
- Has clear success criteria
- Would benefit from specialized tool access

For each candidate, provide:
- **Name**: Suggested agent name
- **Trigger**: When to spawn this agent
- **Autonomy level**: How much it can do without asking

### Candidates for CLAUDE.md
Identify patterns that belong in project-level or global CLAUDE.md instructions:
- Coding conventions that are repeatedly corrected
- Project-specific preferences the user states often
- Tool preferences or workflow rules
- Anti-patterns the user has to repeatedly correct

For each candidate, provide:
- **Instruction**: The exact line to add to CLAUDE.md
- **Scope**: Global (`~/.claude/CLAUDE.md`) or project-specific
- **Evidence**: Which sessions show this pattern

## Step 4: Prioritize

End with a prioritized action list:
1. **Quick wins** - Small changes with high impact (CLAUDE.md additions, simple skills)
2. **High value** - Larger efforts that would significantly improve daily workflow
3. **Nice to have** - Lower priority but worth tracking

Format as a numbered list with estimated effort (trivial / small / medium / large).
