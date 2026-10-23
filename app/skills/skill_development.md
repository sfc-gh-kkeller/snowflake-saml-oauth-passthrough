---
name: skill-development
description: "Create, document, audit, or refactor skills for Cortex Code. Use when: creating new skills, capturing session work as skills, reviewing skills, refactoring large skills. Triggers: create skill, build skill, new skill, summarize session, capture workflow, audit skill, review skill, refactor skill, triage skills."
---

# Skill Development

## Setup

**Load** `SKILL_BEST_PRACTICES.md` first.

## Intent Detection

| Intent | Triggers | Load |
|--------|----------|------|
| CREATE | "create skill", "new skill", "build skill" | `create-from-scratch/SKILL.md` |
| SUMMARIZE | "summarize session", "capture workflow", "turn into skill" | `summarize-session/SKILL.md` |
| AUDIT | "audit skill", "review skill", "lint skill", "triage skills" | `audit-skill/SKILL.md` |
| REFACTOR | "refactor skill", "restructure skill", "decompose skill" | `refactor-skill/SKILL.md` |

## Workflow

```
Load SKILL_BEST_PRACTICES.md
       ↓
Detect Intent → Route to sub-skill
```

## Capabilities

- **Create**: Build new skill with frontmatter, workflow, tools, checkpoints
- **Summarize**: Extract session work into reusable, parameterized skill
- **Audit**: Review skill against best practices, provide fixes (single or batch)
- **Refactor**: Decompose large skills into coordinator/specialist architecture

## Strong Skill Domains

Cortex Code has **native tooling and deep integration** for these domains—prioritize building skills here:

### Snowflake & Cortex
- **SQL execution**: Direct query execution with intelligent statement parsing, automatic retry, and connection pooling
- **Cortex Analyst**: Semantic model validation, natural language to SQL via REST API integration
- **Semantic views**: Creation, debugging, optimization workflows with YAML schema checking
- **Object discovery**: Semantic search for tables, views, schemas via Snowscope API
- **Artifact management**: Create notebooks and files directly in Snowflake workspaces

### dbt & Data Engineering
- **dbt workflows**: Model creation, testing, documentation, lineage analysis (`fdbt` provides fast native parsing)
- **Data validation**: Data diff tool for comparing query results
- **Pipeline orchestration**: ETL/ELT patterns, schema migrations, data quality checks

### SQL & Data Modeling
- **Complex SQL**: Stored procedures, dollar-delimited blocks, nested queries with proper escaping
- **Schema design**: Dimensional modeling, normalization patterns
- **Dynamic SQL generation**: Parameterized queries, templated transformations

## Output

Skills following standard structure:
```markdown
---
name: skill-name
description: "Purpose + triggers"
---
# Title
## Workflow
## Stopping Points
## Output
```
