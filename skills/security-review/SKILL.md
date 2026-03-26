---
name: security-review
description: Review code for trust boundaries, privilege issues, unsafe inputs, secrets exposure, and misuse of capabilities.
---
# Security Review

## Use when
- A change touches permissions, secrets, auth, network access, or untrusted input.

## Quick rules
- Identify trust boundaries first.
- Minimize capability exposure.
- Treat filesystem, shell, browser, and network inputs as hostile by default.
- Check for secrets leakage, unsafe defaults, and missing validation.
- Prefer explicit allowlists over implicit trust.

## Review checklist
- Can an attacker influence the control flow?
- Can data escape the intended namespace?
- Are logs, errors, and telemetry leaking sensitive content?
