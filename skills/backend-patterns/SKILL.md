---
name: backend-patterns
description: Design backend code with clear contracts, validation, idempotency, observability, and failure-aware APIs.
---
# Backend Patterns

## Use when
- You are working on services, APIs, or data processing code.

## Quick rules
- Validate inputs at the boundary.
- Make writes idempotent when retries are possible.
- Return stable error shapes and stable success shapes.
- Keep transactions short and explicit.
- Add logging and metrics where they help diagnosis.

## Review checklist
- Is the API contract easy to reason about?
- Are retries safe?
- Are partial failures visible?
