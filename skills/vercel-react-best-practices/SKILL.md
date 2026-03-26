---
name: vercel-react-best-practices
description: Build React apps for Vercel with sane server/client boundaries, deployment-aware defaults, and minimal footguns.
---
# Vercel React Best Practices

## Use when
- You are targeting Vercel or a Next.js-style deployment.

## Quick rules
- Keep server/client boundaries explicit.
- Prefer simple data flow over clever abstractions.
- Treat environment variables and runtime config as deployment concerns.
- Keep bundle size and hydration cost in mind.
- Verify the app in the same deployment shape it will ship with.

## Good habits
- Use framework conventions before custom plumbing.
- Prefer clear loading and streaming behavior over hidden suspense chains.
