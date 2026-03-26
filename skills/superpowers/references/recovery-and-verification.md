Use this checklist when the task is large, risky, or easy to overfit:

- Scout the current code and runtime evidence first.
- Verify each slice with the narrowest useful check.
- If output looks truncated or malformed, inspect the control loop before trusting the result.
- Prefer a clean retry over stacking more unverified changes on top of a partial result.
- Report what changed, how it was verified, and what still needs work.

In AgentOS specifically:

- Distinguish token limits from scheduler or tool-budget limits.
- Watch for raw tool markup, waiting states, and quota exhaustion.
- Resume from checkpointed state instead of redoing successful work.
