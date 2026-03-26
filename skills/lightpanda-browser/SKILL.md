---
name: lightpanda-browser
description: Use the browser_fetch tool for lightweight browser retrieval, with Lightpanda when available and HTTP fallback when it is not.
---
# Lightpanda Browser

## Use when
- You need to inspect a live webpage, extract text, or follow links.

## Quick rules
- Start with `browser_fetch`.
- If Lightpanda is installed, the tool will use it automatically.
- If the page is dynamic, browser fetch is preferred over raw search snippets.
- Keep the browser context focused on the exact page or URL you need.

## Progressive disclosure
- Use the tool result first.
- Open the full skill file only if you need browser-specific follow-up behavior.
- Combine with web search when you need discovery before retrieval.
