---
name: clickhouse-io
description: Work with ClickHouse using batch-friendly IO, column-oriented schemas, and ingestion patterns that avoid row-by-row overhead.
---
# ClickHouse IO

## Use when
- You are reading, writing, or modeling ClickHouse data.

## Quick rules
- Prefer batch inserts over per-row writes.
- Model columns for query access, not for row-oriented comfort.
- Keep partitioning and sorting keys intentional.
- Watch type choices, nullability, and cardinality.
- Move expensive transforms out of hot query paths when possible.

## Good habits
- Verify queries with realistic volume.
- Prefer stable ingestion contracts over ad hoc writes.
