---
name: make-repeatable
description: "Analyze recent work and propose how to make it repeatable. Use when the user says \"make this repeatable\", \"automate this\", \"I want to do this again\", \"turn this into a command\", or discusses creating reusable workflows."
---

# Make This Repeatable

Analyze the current conversation to identify what work should be made repeatable, then recommend whether to implement it as a **skill** or a **plugin**, and build it upon user approval.

## When This Skill Applies

- User says "make this repeatable"
- User wants to automate a workflow they just performed
- User asks to "turn this into a command"
- User says "I'll need to do this again"
- Discussions about creating reusable patterns

---

## Phase 1: Analysis

### Step 1: Identify the Repeatable Work

Review the conversation history to identify:
1. **What was accomplished** - The end result or goal
2. **Key steps taken** - The sequence of actions
3. **Tools used** - Which Claude Code tools were involved
4. **Inputs required** - What information was needed from the user (these become $ARGUMENTS)
5. **Outputs produced** - Files created, commands run, results generated

### Step 2: Classify the Complexity

| Complexity | Characteristics |
|------------|-----------------|
| **Simple** | Single task, no external tools, just instructions |
| **Moderate** | Multi-step workflow, uses standard tools (Read, Edit, Bash) |
| **Complex** | Requires external APIs, custom tools, or persistent state |

### Step 3: Evaluate Skill vs Plugin

**Recommend a SKILL when:**
- The workflow is primarily instructional (guiding Claude's behavior)
- No new tools or capabilities are needed
- Standard Claude Code tools suffice (Bash, Read, Edit, Grep, etc.)
- The pattern is a sequence of prompts/instructions
- No external service integration required
- No persistent configuration or state needed

**Recommend a PLUGIN when:**
- New tool capabilities are needed (custom tools)
- External API/service integration required (MCP servers)
- Hooks are needed (PreToolUse, PostToolUse, Stop)
- Multiple related skills should be bundled together
- Specialized agents are required
- Custom configuration/settings need to be stored
- The functionality extends Claude Code itself

### Step 4: Recommend Scope

Determine where the skill/plugin should live based on who benefits and what it touches:

| Scope | Location | Format | Namespacing |
|-------|----------|--------|-------------|
| **Project** | `.claude/commands/` in the repo | Single `.md` file per command | Subdirectories → `namespace:command` (e.g., `myteam/deploy.md` → `/myteam:deploy`) |
| **User** | `~/.claude/skills/` | `skill-name/SKILL.md` directory | Flat only — no colon namespacing (use hyphen prefixes like `myteam-deploy`) |
| **Plugin** | `~/.claude/plugins/` | Plugin manifest + skills | Plugin name is the namespace |

**IMPORTANT:** Project-level `.claude/skills/` exists but does NOT support colon-based namespacing via subdirectories. Use `.claude/commands/` for project-scoped commands that need `namespace:name` format.

**Recommend PROJECT scope when:**
- The skill references project-specific paths, conventions, or file formats
- It only makes sense in the context of this repo (e.g., "add status to docs in this project's format")
- Other contributors to the repo would benefit from it
- Use `.claude/commands/namespace/command.md` for namespaced commands

**Recommend USER scope when:**
- The skill is a general personal workflow pattern (e.g., "clean up a transcript", "review PR comments")
- It works across any project the user works on
- It reflects the user's personal preferences or style
- Use `~/.claude/skills/skill-name/SKILL.md` (no colon namespacing — use hyphens)

**Recommend PLUGIN scope when:**
- Already recommending a plugin (from Step 3) — plugins always live in `~/.claude/plugins/`

### Step 5: Present Recommendation

Present this format and ask user to confirm or adjust:

```markdown
## Repeatability Analysis

### What You Did
[Summary of the work performed in this conversation]

### Key Steps
1. [Step 1]
2. [Step 2]
...

### Inputs Required
- [Input 1]: [Description]
- [Input 2]: [Description]

### Recommendation: [SKILL / PLUGIN]

**Why [Skill/Plugin]:**
[2-3 bullet points explaining the choice]

### Scope: [PROJECT / USER / PLUGIN]

**Why [scope]:**
[1-2 bullet points explaining why this scope fits]

**Location:** `[exact path where the file will be created]`

### Proposed Implementation

**Name:** `[suggested-name]`
**Trigger:** `/[command-name] [arguments]`

**What it will do:**
[Brief description]

---

Ready to build this? (Yes / Adjust name / Change scope / Switch to [skill/plugin])
```

## Decision Matrix

| Factor | Skill | Plugin |
|--------|-------|--------|
| Just prompt/instructions | Yes | Overkill |
| Needs new tools | No | Yes |
| External API integration | No | Yes (MCP) |
| Multiple related commands | Consider bundling | Yes |
| Needs hooks | No | Yes |
| Needs agents | No | Yes |
| Needs settings UI | No | Yes |
| One-off automation | Yes | No |
| Sharable with others | Possible | Better |

---

## Phase 2: Implementation

Once the user confirms, proceed to build.

### If Building a SKILL

Create at the path determined by the recommended scope:

- **Project scope:** `.claude/commands/[namespace]/[command-name].md` (in the repo root)
  - Supports colon namespacing via subdirectories: `myteam/deploy.md` → `/myteam:deploy`
  - Format: plain markdown, first line is the description, no YAML frontmatter
  - Use `$ARGUMENTS` for user-provided arguments
- **User scope:** `~/.claude/skills/[skill-name]/SKILL.md` (in the home directory)
  - Flat directory only — no colon namespacing (use hyphens: `myteam-deploy`)
  - Format: YAML frontmatter with `name` and `description`, then markdown body

```markdown
---
name: [skill-name]
description: [One sentence describing when this skill applies. Include trigger phrases like "Use when the user says X, Y, or Z".]
---

# [Skill Title]

[Brief description of what this skill does]

## When This Skill Applies

- [Trigger phrase 1]
- [Trigger phrase 2]
- [Context when this is useful]

## Inputs

This skill accepts arguments: `/[skill-name] [arg1] [arg2]`

- **$ARGUMENTS**: [What the arguments represent]

Or if specific named inputs:
- **arg1**: [Description]
- **arg2**: [Description]

## Process

### Step 1: [First Action]
[Instructions for Claude]

### Step 2: [Second Action]
[Instructions for Claude]

...

## Output Format

[What the skill should produce - files, messages, etc.]

## Tools to Use

- **[Tool1]**: [When/why to use it]
- **[Tool2]**: [When/why to use it]

## Examples

### Example 1
Input: `/[skill-name] example-input`
Result: [What happens]
```

**After creating the skill:**
1. Verify the file was created: `ls ~/.claude/skills/[skill-name]/`
2. Tell the user: "Skill created! You can now use `/[skill-name]` or say '[trigger phrase]'"
3. Offer to test it immediately

### If Building a PLUGIN

Use the Skill tool to invoke `plugin-dev:create-plugin` with context about what to build:

```
/plugin-dev:create-plugin

Context from conversation:
- Goal: [What the plugin should accomplish]
- Components needed:
  - Skills: [List skills if any]
  - Agents: [List agents if any]
  - Hooks: [List hooks if any]
  - MCP servers: [List MCP integrations if any]
- Key workflows: [The steps identified earlier]
- Inputs: [What the user provides]
- Outputs: [What gets produced]
```

The plugin-dev:create-plugin skill will handle:
1. Scaffolding the plugin structure
2. Creating the manifest
3. Implementing each component
4. Validating the plugin

---

## Examples

### Skill Examples
- "Clean up a YouTube transcript" → Skill (just instructions)
- "Create a commit with conventional format" → Skill (Bash + instructions)
- "Review PR comments and reply" → Skill (gh CLI + instructions)
- "Search Gmail for emails" → Skill (wraps gog CLI)

### Plugin Examples
- "Integrate with Gmail" → Plugin (needs MCP server, auth, multiple commands)
- "Add code review agents" → Plugin (needs custom agents)
- "Prevent certain file edits" → Plugin (needs hooks)
- "Bundle my 5 related skills" → Plugin (organization)

---

## Quick Reference: Skill File Location

Skills go in: `~/.claude/skills/[skill-name]/SKILL.md`

Required frontmatter:
```yaml
---
name: skill-name
description: Description including trigger phrases
---
```

The description in frontmatter is critical - it tells Claude when to use this skill.
