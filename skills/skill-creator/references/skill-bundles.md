Keep skill bundles shallow and predictable:

- `SKILL.md` holds the trigger and the shortest useful workflow.
- `references/` holds detailed variants, conventions, and examples.
- `scripts/` holds deterministic helpers that are better executed than retyped.
- `assets/` holds templates or output resources that should not be loaded into context by default.
- `agents/openai.yaml` can hold UI-facing metadata for skill pickers and chips.

Use progressive disclosure:

- Read `SKILL.md` first.
- Open one reference file only when the current task needs that variant.
- Prefer running or patching a script instead of copying a long procedure into chat.
