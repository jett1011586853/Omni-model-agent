---
name: Superpowers
description: High-leverage engineering workflow: scout first, plan in small slices, execute carefully, verify, repair, and report clearly.
---
# Superpowers

## Use when
- The task is non-trivial, multi-step, or easy to overfit.
- You need a steady engineering workflow instead of a one-shot answer.

## Core loop
1. Scout the codebase and current behavior.
2. Plan the smallest meaningful slice.
3. Execute one slice.
4. Verify it with the narrowest useful check.
5. Repair regressions before moving on.

## Reporting
- Say what changed.
- Say how you verified it.
- Call out residual risks.
- Suggest the next slice only after the current one is stable.

## Bundled resources
- See `references/recovery-and-verification.md` for the longer reliability checklist.
- See `agents/openai.yaml` for UI-facing skill metadata.
