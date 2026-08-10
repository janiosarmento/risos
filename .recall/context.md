# Project Context — risos (updated 2026-07-12T22:52:39)

_Generated locally by Recall — TextRank (vendored, numpy-accelerated)._

## 🎯 Goal
O app do Risos está muito, muito bom. A única melhoria de que ele precisa é a possibilidade de ocultar e exibir a sidebar sob demanda. É muito complicado de implementar essa melhoria?

## 🧭 Summary
- Fase 1: S2 (rate limit login), S4 (auth no proxy), S7 (allowlist validate-secret), S8 (cookie secure configurável), Y3 (imports mortos).
- Commit da fase 1 (fora PROMPTS.md e beads, que não são meus):
- Fase 2: S1+D1 (helper único SSRF-safe pra URL), S3 (XSS via resumo LLM), S5 (SVG no proxy), S6 (CSP/SRI), S10 (timeouts do proxy).
- Agora smoke test do url_safety e do proxy com SSRF:
- Agora full-app smoke test:
- Sem servidor aqui — não dá pra validar nginx/CSP ao vivo nem abrir no browser.
- Agora atualizo a tabela da seção 5 e a nota do rodapé pra refletir que S1–S8, S10, D1, Y3 estão todos resolvidos, restando S9, S11 (baixa prioridade, fora de escopo das fases 1/2) e fases 3–6:
- Sidebar toggle uses `sidebarOpen: false` (app.js:47), set via inline `@click="sidebarOpen = true/false"` (template lines 268, 290, 565) and programmatically reset on mobile at app.js:1105.

## ⏭️ Next steps / open threads
- **Bug que achei e corrigi no processo:** minha primeira versão de `url_safety.py` tinha um erro de fail-closed que fazia **todo hostname não-literal-IP falhar** (inclusive `example.com`) — pego pelo próprio smoke test antes de commitar.
- É muito complicado de implementar essa melhoria?
- Quer que eu comite essas mudanças agora?
- Uncommitted changes to wrap up: .beads/issues.jsonl, PROMPTS.md, .recall/, backend/.recall/

## 📂 Files touched
- /Users/janiosarmento/projects/risos/htdocs/index.template.html
- /Users/janiosarmento/projects/risos/htdocs/static/js/app.js
- /Users/janiosarmento/projects/risos/htdocs/static/locales/pt-BR.json
- /Users/janiosarmento/projects/risos/htdocs/static/locales/en-US.json
- /Users/janiosarmento/projects/risos/htdocs/index.html

## 🔧 Commands run
- grep -n "icon-hamburger\|icon-sidebar\|icon-panel\|icon-collapse\|<symbol" /Users/janiosarmento/projects/risos/htdocs/index.template.html | head -40
- grep -rln "openMenu" /Users/janiosarmento/projects/risos/htdocs/ 2>/dev/null
- grep -n "openMenu\|closeMenu" /Users/janiosarmento/projects/risos/htdocs/static/locales/pt-BR.json /Users/janiosarmento/projects/risos/htdocs/static/locales/en-
- grep -n "APP_VERSION" /Users/janiosarmento/projects/risos/htdocs/index.html | head -3
- grep -n "APP_VERSION" /Users/janiosarmento/projects/risos/htdocs/index.template.html
- cd /Users/janiosarmento/projects/risos/backend && python -m app.html_assembler
- grep -n "toggleDesktopSidebar\|desktopSidebarOpen" /Users/janiosarmento/projects/risos/htdocs/index.html | head -5
- d=/Users/janiosarmento/projects/risos; grep -Hm1 '^description:' "$d"/.claude/skills/*/SKILL.md 2>/dev/null; ls "$d"/.claude/skills 2>/dev/null
- cd /Users/janiosarmento/projects/risos && cat backend/README* 2>/dev/null | head -30; find . -maxdepth 2 -iname "*.env*" -o -iname "docker-compose*" 2>/dev/null
- docker compose ps 2>&1 | head -20
- which docker; docker ps 2>&1 | head -20
- cat docker-compose.yml | head -40
- cd /Users/janiosarmento/projects/risos/backend && cat requirements.txt 2>/dev/null | head -5; ls
- ls -la | grep -i venv; python3 --version; cat .env.example | grep -i port
- python3 -m venv /tmp/risos-venv 2>&1 | tail -5 && /tmp/risos-venv/bin/pip install -q -r requirements.txt 2>&1 | tail -20
- …and 6 more

## ⏱ Where we left off
Valeu! Fechado. 🤙

## 🌿 Git ground-truth
```
Uncommitted changes (git diff --stat):
PROMPTS.md | 410 +++++++++++++++++++++++++++++++++++++++++++++++--------------
 1 file changed, 317 insertions(+), 93 deletions(-)

Recent commits:
ffb46f1 feat: add desktop sidebar hide/show toggle
0260af1 refactor: extract _build_tag_indexes from suggest_merges (K3)
d6b185c refactor: decompose _job_process_summaries into 3 helpers (K2)
ddf30f1 refactor: decompose _call_model into composable helpers (K6)
27c0b76 fix: second layer — sentence boundary ignores single-letter initials
cb609f6 refactor: data-driven update_preferences loops for simple fields (K4)
19ea1a9 fix: handle single-letter initials in paragraph splitting
825a97c fix: _apply_post_filters must expose topic_tags and feed_ids_list
```
