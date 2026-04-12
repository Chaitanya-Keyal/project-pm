# LensClient returns raw datetime objects

## Context
LensClient dataclasses (`PRDetail`, `IssueDetail`, etc.) return `datetime` objects directly from SQLAlchemy — they are not pre-converted to strings.

## Why this matters
PM's Jinja2 `days_ago` filter originally expected string input because the early `build_pr_detail()` function ran all datetimes through a `_to_str()` helper before constructing the `DetailView`. When the issue detail path was added, it passed raw datetimes to the template and hit `TypeError: 'datetime.datetime' object is not subscriptable`.

## Resolution
- The `days_ago` filter now accepts both `datetime` and `str` inputs (checks `isinstance` first)
- `_to_str()` was removed from `board_service.py` — the filter is the right place for type coercion
- `DetailView` type annotations changed from `str | None` to `datetime | None` for date fields
- The PR detail template no longer uses `[:19]` string slicing on dates

## Principle
Jinja2 filters that consume model data should handle the types that the data layer actually produces. Don't add conversion layers in the service to work around brittle filters.
