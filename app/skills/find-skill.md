---
name: find-skill
description: >-
  Find, add, check, or update Cortex Code catalog skills before using them.
  Use when the user asks to discover available skills, install a catalog
  skill, make an uninstalled `/skill` or `$skill` usable, search the skill
  marketplace/catalog, check whether installed skills have updates, or update
  skills from the catalog, stage, GitHub, or tarball sources. Do not use this
  for public Snowflake Marketplace datasets or apps; use marketplace-search for
  third-party data/product listings.
---

# Find Skill

Use this skill to discover Cortex Code skills from the skill catalog and make
them available locally before invoking them.

## Workflow

1. Search for candidate skills:

```bash
cortex skill find "<query>"
```

Use a short query based on the capability the user needs. If the user named a
specific saved Snowflake connection, pass `--connection <name>`.

2. Choose by the catalog result's name, description, source, and plugin FQN.
Do not rely on the catalog object's SQL name alone; a Cortex Extension object
name can differ from the actual `name` in `SKILL.md`.

3. Install the selected skill before trying to invoke it. Prefer the exact
command printed by `cortex skill find`; it preserves important options such as
`--connection`. For plugin-backed catalog results, that
usually looks like:

```bash
cortex skill add <catalog-name> --plugin-fqn <DB.SCHEMA.CORTEX_EXTENSION>
```

If the user provided a share URI directly, install it as-is:

```bash
cortex skill add snow://skill_catalog/<DB>.<SCHEMA>.<CORTEX_EXTENSION>
```

4. Confirm the installed skill name:

```bash
cortex skill list
```

Use the installed skill's real `SKILL.md` name for future `$skill` or `/skill`
references. The install output and `cortex skill list` are authoritative.

5. If the user needs the newly installed skill used in the same turn, inspect
the installed skill's `SKILL.md` from the listed path and follow its
instructions directly. A running agent may not auto-load a skill that was
installed after the prompt was parsed, so do not assume `$skill` or `/skill`
will resolve until a later turn.

If the user is testing from a source checkout and provides a CLI prefix such as
`bun run dev --`, use that prefix consistently in place of `cortex`.

## Updates

Check installed remote, stage, tarball, and catalog skills:

```bash
cortex skill check
```

Check one source or skill:

```bash
cortex skill check <skill-or-source>
```

Update an installed skill with the command shown by `check`, or use the
appropriate source form:

```bash
cortex skill update <skill-or-source>
cortex skill update <skill-name> --plugin-fqn <DB.SCHEMA.CORTEX_EXTENSION>
```

## Snowsight Sandbox

When running in a sandbox and skills should persist in the workspace, set:

```bash
export SKILL_DIR=/workspace/.snowflake/cortex/skills
```

Then run the same `cortex skill add`, `check`, and `update` commands. The skill
registry is stored beside `SKILL_DIR` so future sandbox sessions can discover
the installed skills.

## Guardrails

- Do not tell the user to use an uninstalled catalog skill with `$skill` or
  `/skill`; install it first.
- Do not assume the catalog SQL object name equals the installed skill name.
- Do not edit `SKILL.md` metadata to force a name match during install; preserve
  the publisher's bundle and use the actual installed skill name.
- Do not use this skill for public Snowflake Marketplace datasets, Native Apps,
  or connectors; use `marketplace-search`.
