# SQLite DROP COLUMN fails silently on UNIQUE-constrained columns

## Context
During removal of the `auth_token` column from the `contributors` table (2026-04-12), `ALTER TABLE contributors DROP COLUMN auth_token` failed silently even on SQLite 3.46.1 (which supports DROP COLUMN since 3.35.0).

## Root cause
SQLite cannot drop a column that participates in a UNIQUE constraint or index. The `auth_token` column had `UNIQUE(auth_token)` in the schema. The error was swallowed by a `try/except` block, making it appear to succeed.

## Solution
Use the standard SQLite table rebuild pattern:
1. `ALTER TABLE contributors RENAME TO _contributors_old`
2. `CREATE TABLE contributors (...)` with the new schema (via `Base.metadata.create_all`)
3. `INSERT INTO contributors (...) SELECT ... FROM _contributors_old`
4. `DROP TABLE _contributors_old`

## Takeaway
For any SQLite column drop in this project, check whether the column has UNIQUE, PRIMARY KEY, or is part of an index. If so, use the table rebuild pattern instead of `ALTER TABLE DROP COLUMN`. The Python and system SQLite versions are both 3.46.1 — the limitation is a SQLite design constraint, not a version issue.
