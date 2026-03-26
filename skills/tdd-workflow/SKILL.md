---
name: tdd-workflow
description: Apply a red-green-refactor loop with a small reproducible failure, a focused fix, and a regression check.
---
# TDD Workflow

## Use when
- You are fixing a bug or implementing a behavior with a clear acceptance check.

## Quick rules
- Reproduce the failure first.
- Write the smallest test that proves the gap.
- Make it pass with the least invasive change.
- Refactor only after the behavior is green.
- Keep one smoke test for the path you touched.

## Good habits
- Prefer deterministic checks over manual reasoning alone.
- Capture the bug in a regression test when possible.
