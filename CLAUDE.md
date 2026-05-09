# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->


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
