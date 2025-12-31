# Progresso da Implementação — Risos (RSS Reader com IA)

**Última atualização:** 2025-12-31
**Fase atual:** Fase 13 concluída — Melhorias de UX
**Repositório:** https://github.com/janiosarmento/risos

---

## Estado Atual

O projeto está em produção com funcionalidades avançadas de IA, incluindo tradução automática de títulos, detecção de páginas de erro, load balancing de API keys, e backfill automático de resumos.

### Instâncias em Produção

| Instância | URL | Backend | Serviço |
|-----------|-----|---------|---------|
| Principal | rss.sarmento.org | porta 8100 | `rss-reader` |
| Israel | israel.sarmento.org | porta 8101 | `risos_israel` |
| Michael | michael.sarmento.org | porta 8102 | `risos_michael` |

### Configuração dos Serviços

Todos os serviços usam gunicorn com proteção contra travamento:
```bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 127.0.0.1:PORT \
    --workers 1 --timeout 120 --max-requests 1000 --max-requests-jitter 50
```

---

## Sessão 2025-12-31 — Melhorias de UX

### ✅ Fase 13.1: Link GitHub na Sidebar
- Rodapé fixo na sidebar com link para o repositório
- Ícone SVG do GitHub + texto "Github"
- Suporte a dark mode

### ✅ Fase 13.2: Atalho de Teclado para Seleção
- Tecla `X` ativa/desativa modo de seleção de posts
- Permite operações em lote (marcar como lido, etc.)

### ✅ Fase 13.3: Descoberta Automática de Feeds
- Novo endpoint `POST /feeds/discover?url=`
- Ao adicionar feed, usuário pode informar URL do site
- Sistema tenta descobrir feed automaticamente:
  1. Verifica se URL já é um feed
  2. Procura tags `<link rel="alternate">` no HTML
  3. Tenta caminhos comuns (`/feed`, `/rss`, `/rss.xml`, etc.)
- Mensagem clara se feed não for encontrado

### Commits da Sessão 2025-12-31

| Hash | Descrição |
|------|-----------|
| `b4895e1` | Add GitHub link to sidebar footer |
| `20eb97a` | Add disclaimer about Docker setup |
| `c66e139` | Add keyboard shortcut 'x' to toggle select mode |
| `24ba73e` | Add automatic feed discovery from site URL |

---

## Sessão 2025-12-29 — Estabilidade e Melhorias de UX

### ✅ Fase 12.1: Prompts Dinâmicos e Personalizáveis
- `prompts.yaml` lido dinamicamente a cada chamada de IA (sem restart)
- Arquivo template: `prompts.yaml.example` (versionado)
- Arquivo produção: `prompts.yaml` (no .gitignore, personalizável)

### ✅ Fase 12.2: Regras de Script Multilíngue
- Regras universais para qualquer idioma de destino
- Especificação de script nativo (Latin, Cyrillic, Hanzi, Hangul, etc.)
- Previne mistura acidental de scripts (ex: chinês em texto português)

### ✅ Fase 12.3: Prevenção de Travamento do Serviço
- Migração de uvicorn direto para gunicorn com UvicornWorker
- `--timeout 120`: mata workers que não respondem em 2 min
- `--max-requests 1000`: reinicia workers periodicamente
- Todos os 3 serviços atualizados

### ✅ Fase 12.4: Otimização de Atualização de Feeds
- UI só atualiza no final do loop de refresh
- Reload só ocorre se houver novos posts

### ✅ Fase 12.5: Backfill de Resumos Órfãos
- Função `_backfill_missing_summaries()` no scheduler
- Roda após cada ciclo de atualização de feeds (30 min)
- Enfileira até 50 posts órfãos por ciclo (prioridade baixa)
- Posts órfãos: têm content_hash mas não têm resumo nem estão na fila

### ✅ Fase 12.6: Contador de Posts na Sidebar
- Formato: "X feeds | Y/Z posts" (não lidos/total)
- Atualizado após refresh, mark read, e operações em lote
- Dados obtidos do endpoint `/admin/status`

---

## Commits da Sessão 2025-12-29

| Hash | Descrição |
|------|-----------|
| `583b1c6` | Load prompts.yaml dynamically |
| `4925d47` | Make prompts.yaml customizable without git conflicts |
| `0b03552` | Make script rules language-agnostic |
| `ac26ced` | Add gunicorn timeout and max-requests |
| `0bf9b72` | Only reload UI after feed refresh if new posts |
| `32c9fd3` | Add backfill for orphan posts and improve sidebar stats |
| `fd4d343` | Fix Docker setup for recent changes |

---

## Arquivos Principais Modificados

```
backend/
├── app/
│   ├── config.py              # load_prompts() exportado
│   └── services/
│       ├── cerebras.py        # Prompts carregados dinamicamente
│       └── scheduler.py       # +_backfill_missing_summaries()
├── prompts.yaml.example       # Template versionado

htdocs/
├── index.html                 # Sidebar: X/Y posts
└── static/js/app.js           # +unreadPostsCount, refresh otimizado

install.sh                     # +gunicorn params, +prompts.yaml copy
.gitignore                     # +backend/prompts.yaml
```

---

## Migrações Alembic

| ID | Nome | Descrição |
|----|------|-----------|
| `172dd9c19d31` | initial_schema | Tabelas e índices originais |
| `28e3af40a708` | add_starred_columns | is_starred, starred_at |
| `73152e004d90` | add_translated_title | translated_title em ai_summaries |

---

## Funcionalidades Implementadas (Resumo)

### IA e Resumos
- Resumos automáticos com Cerebras (Llama 3.3 70B)
- Tradução automática de títulos
- Detecção de páginas de erro/lixo (economiza tokens)
- Load balancing de múltiplas API keys
- Backfill automático de posts órfãos

### Frontend
- Interface responsiva com Alpine.js + Tailwind
- Atalhos de teclado (J/K navegação, Enter abre, R refresh)
- Modo escuro
- Favoritos (estrela)
- Renderização Markdown nos resumos

### Backend
- FastAPI + SQLAlchemy + SQLite (WAL mode)
- Scheduler com jobs: update_feeds, process_summaries, cleanup, backfill
- Circuit breaker para API externa
- Rate limiting por IP

---

## Como Retomar o Desenvolvimento

### 1. Verificar serviços
```bash
sudo systemctl status rss-reader risos_israel risos_michael
```

### 2. Verificar logs
```bash
journalctl -u rss-reader -f
tail -f /var/log/rss-reader/error.log
```

### 3. Verificar fila de resumos
```bash
sqlite3 /var/www/rss.sarmento.org/backend/data/reader.db \
    "SELECT COUNT(*) FROM summary_queue"
```

### 4. Verificar posts órfãos
```bash
sqlite3 /var/www/rss.sarmento.org/backend/data/reader.db "
SELECT COUNT(*) FROM posts p
WHERE p.content_hash IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM ai_summaries a WHERE a.content_hash = p.content_hash)
AND NOT EXISTS (SELECT 1 FROM summary_queue q WHERE q.content_hash = p.content_hash);
"
```

### 5. Rodar migrações
```bash
cd /var/www/rss.sarmento.org/backend
source venv/bin/activate
alembic upgrade head
```

---

## Configuração de API Keys

```bash
# Em backend/.env - múltiplas keys separadas por vírgula
CEREBRAS_API_KEY=key1,key2,key3
```

Round-robin automático. Keys com 429 entram em cooldown de 60s.

---

## Próximas Ideias (Backlog)

- [ ] Busca de posts por título/conteúdo
- [ ] Tags/labels customizadas
- [ ] PWA com service worker
- [ ] Estatísticas de leitura
- [ ] Suporte a outros provedores de IA

---

## Arquivos de Referência

- `PROJETO.md` — Especificação técnica completa
- `PLANO.md` — Plano de implementação por fases
- `PROGRESSO.md` — Este arquivo (save game)
- `README.md` — Documentação pública
