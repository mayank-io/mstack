---
name: setup-config
description: Use when the user says "set up mstack config", "create ~/.mstack", "seed my mstack config", "init mstack", or when an mstack skill reports a missing file under ~/.mstack. Creates the per-user config directory from the defaults each installed mstack plugin ships, without overwriting anything already there.
---

# Set Up mstack Config

Every mstack plugin keeps its user-editable config in `~/.mstack/<plugin>/` and ships the starting files in its own `config-defaults/` directory. This skill copies those defaults into place.

| Plugin | Seeded file | Read by |
|---|---|---|
| `dev` | `~/.mstack/dev/feedback-tags.json` | `dev:apply-feedback`, `dev:review-feedback` |
| `notes` | `~/.mstack/notes/channels/example.md` | `notes:clip` (channel templates) |

## Procedure

1. Preview, then seed:

   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT unset}/scripts/seed_config.py" --dry-run
   python3 "${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT unset}/scripts/seed_config.py"
   ```

   Run it outside the command sandbox when the sandbox blocks writes to `~/.mstack`. Each output line is `created <path>` or `kept <path>`. A file that exists is never overwritten.

2. Exit code 2 means the installed-plugins manifest could not be read and nothing was written. Report that; do not create the files by hand.

3. Report the `created` and `kept` lines to the user as they are.

## Keeping the config in a private repo

`~/.mstack` holds personal settings, so it belongs in a private repository, never in a public one. To put an existing directory under version control:

```bash
cd ~/.mstack && git init && git add -A && git commit -m "mstack config"
git remote add origin <private repo url> && git push -u origin main
```

On another machine, clone that repository to `~/.mstack` first, then run this skill: it fills in only the files the clone does not have.

Do not create or push a repository unless the user asks for it.
