# Progresso da Implementação — Risos (RSS Reader com IA)

**Última atualização:** 2026-01-02
**Fase atual:** Fase 14 concluída — Melhorias de i18n e UX
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

## Sessão 2026-01-02 — Melhorias de i18n e UX

### ✅ Fase 14.1: Confirmação para "Marcar Todos como Lidos"
- Diálogo de confirmação antes de marcar posts como lidos
- Mensagem contextual: mostra quantidade e contexto (feed/categoria/todos)
- Previne cliques acidentais

### ✅ Fase 14.2: Correção de Strings Hardcoded
- Removidas strings em português hardcoded em `refreshFeeds()`
- Todas as mensagens de toast agora usam sistema de i18n
- Adicionadas chaves `refresh.updating`, `refresh.newPosts`, `refresh.noNewPosts`

### ✅ Fase 14.3: Tradução de Erros do Backend
- Função `translateError()` mapeia mensagens do backend para i18n
- Seção `backendErrors` nos arquivos de locale (18 mensagens)
- Erros como "Feed not found" aparecem traduzidos no idioma do usuário

### ✅ Fase 14.4: Modal de Confirmação Customizado
- Substituição do `confirm()` nativo por modal estilizado
- Backdrop com blur (`backdrop-blur-sm`)
- Botão OK focado automaticamente (usuário pode apertar Enter)
- Suporte a Escape para cancelar
- Visual consistente com dark/light mode

### ✅ Fase 14.5: Atalhos de Teclado Visíveis
- Botões mostram tecla de atalho: Refresh (R), Select (X), Mark as read (M)
- Barra de dicas no rodapé da lista: J/K navegar, Enter abrir, Space marcar
- Dicas visíveis apenas em desktop (ocultas no mobile)
- Traduções adicionadas para atalhos

### Commits da Sessão 2026-01-02

| Hash | Descrição |
|------|-----------|
| `109059c` | Add confirmation dialog before marking all posts as read |
| `3879462` | Fix hardcoded Portuguese strings in feed refresh toasts |
| `0f087b2` | Fix remaining hardcoded English strings in error messages |
| `301ca64` | Add translation for backend error messages |
| `d0343e0` | Add custom confirm modal with backdrop blur |
| `2fc773b` | Add keyboard shortcut hints to UI (desktop only) |

---

## Sessão 2025-12-31 — Melhorias de UX

### ✅ Fase 13.1: Link GitHub na Sidebar
- Rodapé fixo na sidebar com link para o repositório
- Ícone SVG do GitHub + texto "Github"
- Suporte a dark mode

### ✅ Fase 13.2: Atalhos de Teclado para Seleção em Lote
- `X` ativa/desativa modo de seleção de posts
- `Espaço` marca/desmarca checkbox do post selecionado
- `M` marca posts selecionados como lidos
- Navegação com `J`/`K` funciona normalmente no modo de seleção

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
| `55e4966` | Add Space key to toggle post selection in select mode |
| `7831dac` | Make M key mark selected posts as read in select mode |

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
