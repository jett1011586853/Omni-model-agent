---
name: skill-creator
description: Create or revise skills for the AgentOS catalog, keeping instructions concise and progressively disclosed.
---
# Skill Creator

## Use when
- You are creating or updating a skill.
- You need to turn a repeated workflow into a reusable agent capability.

## Quick rules
- Keep `SKILL.md` lean.
- Put long variants, examples, and references into `references/`.
- Put executable helpers into `scripts/` when the workflow is deterministic.
- Make the frontmatter description specific enough to trigger the right task.

## Update workflow
1. Scout the current behavior and required surface area.
2. Write only the essential instructions.
3. Add references only for details that would bloat the main file.
4. Validate the skill against a realistic task before calling it done.

## Bundled resources
- See `references/skill-bundles.md` for a compact bundle layout guide.
- See `agents/openai.yaml` for UI-facing skill metadata.
