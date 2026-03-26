---
name: frontend-patterns
description: Build frontend features with clean component boundaries, grounded state, accessibility, and predictable UI behavior.
---
# Frontend Patterns

## Use when
- You are changing React or frontend application code.

## Quick rules
- Keep state close to where it is used.
- Split components by responsibility, not by convenience.
- Model loading, empty, error, and retry states explicitly.
- Prefer accessibility-friendly markup first, then styling.
- Avoid leaking business logic into presentation components.

## Review checklist
- Does every interactive element work with keyboard input?
- Are async and error paths visible?
- Are file and data dependencies easy to trace?
