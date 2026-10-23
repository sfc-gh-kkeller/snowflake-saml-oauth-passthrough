---
name: sql-author
description: "Use for ANY task that involves writing, running, or debugging SQL against Snowflake tables. Helps find the right table, verify columns exist, avoid timeouts on large tables, and validate joins. Triggers: write a query, sql for, query this table, author sql, build a query, fix this query, how many, how much, show me data, explore this table, describe table, select from."
---

# SQL Author

Write correct SQL by verifying every assumption before the query runs.

## Rules

1. **DESCRIBE before SELECT.** Run `DESCRIBE TABLE <db.schema.table>` before writing any query. Use only columns that appear in the output. Never guess a column name.

2. **Verify tables exist.** Before querying — and before telling the user a table *doesn't* exist — run `SHOW TABLES LIKE '<name>' IN SCHEMA <db.schema>` (try SHOW VIEWS too). If the user gives just a name, use `cortex search object "<name>"` to find it. Multiple candidates? Ask the user.

3. **Verify unfamiliar functions.** If you're not certain a Snowflake function exists, check first: `cortex search docs "<function_name>"` or test with a minimal `SELECT <function>('test')`. Don't invent functions.

4. **Check table size.** Query `INFORMATION_SCHEMA.TABLES` for `ROW_COUNT` before running against unfamiliar tables. Over 1B rows? Add date/partition filters. Over 100B? Filter on all clustering keys. No filters specified by user? Default to last 1 day and say so.

5. **State assumptions, ask if unsure.** Before executing, tell the user: which table, what date range, what filters, how you're computing the metric. If any of these feel like guesses, stop and ask — a one-turn clarification beats a confident wrong answer.

6. **Check for semantic views.** Before writing complex SQL, try `cortex semantic-views search "<topic>"`. Semantic views have verified metric definitions — prefer them when available.

7. **Default to LEFT JOIN.** NULLs in join keys silently drop rows with INNER JOIN. Before joining, check cardinality on both sides — if both have duplicates, pre-aggregate one side in a CTE.

8. **Re-read the request before executing.** Did they ask to exclude something you didn't filter? Ask for a specific column you missed? Want the *whole* statement, not a fragment? Check.

9. **Sanity-check results.** If a query returns 0 rows, don't just report it — investigate whether filters are too restrictive or you picked the wrong table. If numbers look implausible, check before presenting conclusions.

10. **Snowflake-specific gotchas.** `!= 'value'` doesn't match NULLs. `COUNT(col)` excludes NULLs, `COUNT(*)` doesn't. Use `QUALIFY` instead of subqueries for window filters. Use `ILIKE` not `LOWER() LIKE`. Use `DIV0NULL` not `DIV0`. Cast `VARIANT` fields explicitly. `ARRAY_CAT` only takes 2 arrays — nest calls for more.

11. **Diagnose permission errors with EXPLAIN_PRIVILEGES.** When a query fails with an access/privilege error, run `CALL EXPLAIN_PRIVILEGES(statement => '<failing_sql>', missing_only => true, for_role => '<role>')` to see exactly which privileges are missing. `missing_only => true` filters out already-granted privileges. `for_role` checks a specific role without switching to it — useful for diagnosing another role's access.
