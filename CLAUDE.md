# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

## Session Completion

When wrapping up a change:

1. **Run quality gates** (if code changed) — tests, linters, builds
2. **Regenerate static HTML** (if front-end changed) — `cd backend && python -m app.html_assembler` to sync `index.html` and `manifest.json` from `index.template.html`
3. **Commit and push** — work is not done until `git push` succeeds

## Build & Test

_Add your build and test commands here_

```bash
# Example:
# npm install
# npm test
```

## Architecture Overview

_Add a brief overview of your project architecture_

## Conventions & Patterns

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org):

```
<type>: <descrição imperativa em inglês>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Exemplos:
- `feat: add keyboard shortcut for marking all as read`
- `fix: resolve relative URLs in feed entries`
- `docs: document versioning convention`
- `refactor: extract URL resolution to helper function`

### Versioning

A versão do app fica em `htdocs/index.html`:

```html
<script>var APP_VERSION = 'YYYYMMDD[letra]';</script>
```

Formato: data do dia (`YYYYMMDD`) + sufixo de letra incrementado a cada build do dia (`a`, `b`, `c`, ...).

**A cada commit com mudança de código, atualizar a versão antes de commitar.**

Exemplos:
- Primeiro build do dia 2026-05-09 → `20260509a`
- Segundo build no mesmo dia → `20260509b`
- Primeiro build do dia seguinte → `20260510a`
