For long-running tasks:

- Break work into slices that can be verified independently.
- Leave durable breadcrumbs in files, not only in chat.
- When a slice is interrupted, resume from the current workspace state before adding new work.
- Record rollback points before risky edits.

For AgentOS tasks:

- Prefer one clear execution step per concrete deliverable.
- If a step is likely to exceed the current tool budget, split it into staged steps.
- Treat `waiting`, `resume`, and checkpoint recovery as normal execution paths, not exceptions.
