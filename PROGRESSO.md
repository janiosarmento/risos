# Progresso da Implementação — Risos

**Última atualização:** 2026-01-20
**Repositório:** https://github.com/janiosarmento/risos

---

## Estado Atual

Projeto em produção com IA (Cerebras), tradução automática de títulos, e múltiplas instâncias.

### Instâncias

| Instância | URL | Porta | Serviço |
|-----------|-----|-------|---------|
| Principal | rss.sarmento.org | 8100 | `rss-reader` |
| Israel | israel.sarmento.org | 8101 | `risos_israel` |
| Michael | michael.sarmento.org | 8102 | `risos_michael` |

### Comando dos Serviços

```bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 127.0.0.1:PORT \
    --workers 1 --timeout 120 --max-requests 1000 --max-requests-jitter 50
```

---

## Sessão 2026-01-20 — Filtro de Favoritos na Lista de Posts

### Filtro de Posts com 3 Estados
- Antes: apenas "Não lidos" e "Todos"
- Agora: "Não lidos", "Todos" e "Favoritos"
- Mobile: ícones compactos (○ círculo, ≡ lista, ★ estrela)
- Desktop: texto completo nos botões

### Contagem Contextual de Favoritos
- Contagem exibida no botão de filtro: `★ 241` (mobile), `Favoritos (241)` (desktop)
- Contagem é contextual:
  - Na visão global → total de favoritos
  - Em uma categoria → favoritos da categoria
  - Em um feed → favoritos do feed
- Backend retorna `starred_count` na resposta de `/api/posts`
- Removida função `loadStarredCount()` obsoleta

### Remoção de "Favoritos" da Sidebar
- Item "Favoritos" removido da sidebar (economia de espaço no mobile)
- Funcionalidade movida para o botão de filtro na lista de posts
- Backend permite combinar `starred_only` com `feed_id`/`category_id`

---

## Sessão 2026-01-07 — Atalhos de Teclado

### Desambiguação da Tecla R
- Antes: `R` = refresh feeds (main view) OU regenerar resumo (post aberto)
- Em split view, era impossível dar refresh com teclado enquanto via um post
- Agora: `R` = refresh feeds (sempre), `Shift+R` = regenerar resumo IA
- Comportamento consistente em modal e split view
- Button hints e traduções atualizados

---

## Sessão 2026-01-06 — Preferências, Configurações e Documentação

### Correção do "Marcar todos como lidos"
- Agora envia apenas os IDs dos posts visíveis na interface
- Posts que chegaram via background refresh são preservados
- Antes: enviava `feed_id`/`category_id` → marcava TODOS os não lidos
- Agora: envia `post_ids` → marca apenas o que o usuário viu

### Correção de Newlines Literais nos Resumos
- LLM às vezes retorna `\\n` (duplo escape) ao invés de `\n`
- Após `json.loads()`, isso vira a string literal `\n`
- Correção no `generate_summary()` após parse do JSON
- Validadores Pydantic em `PostResponse`/`PostDetail` para corrigir ao servir
- Funciona para dados existentes sem modificar o banco

### Melhorias no Rate Limiting da API Cerebras
- Reset automático de estado no startup (circuit breaker, cooldowns da fila)
- Verificação prévia de chaves disponíveis antes de processar item da fila
- Erro "All API keys in cooldown" não conta mais como tentativa do item
- Cooldown de chave aumentado de 60s para 5 minutos após 429
- Novo endpoint `GET /api/admin/queue-status` para monitorar fila e chaves
- Novo endpoint `POST /api/admin/clear-queue-cooldowns` para resetar fila
- Log detalhado de erros 429 com headers de retry-after
- `CEREBRAS_MAX_RPM` reduzido de 20 para 6 (mais conservador)

### Proteção de Exclusão de Feeds
- Feeds com posts favoritos não podem ser excluídos
- Backend retorna erro 400 se tentativa de deletar feed com starred posts
- Frontend esconde botão de deletar e mostra ícone de estrela com tooltip
- Campo `starred_count` adicionado ao schema `FeedResponse`
- Subquery para contagem de posts favoritos em `list_feeds`

### Documentação para IA
- Novo `AI.md` com guia completo para desenvolvimento assistido por IA
- Seção sobre como usar Claude Code neste projeto
- Exemplos de prompts e padrões que funcionam bem
- `PROJETO.md` renomeado para `PROJECT.md` e traduzido para inglês
- Removido `PROJETO.md` do `.gitignore`

### Preferências Persistentes
- Nova API `/api/preferences` (GET/PUT) para locale e theme
- Preferências salvas em `app_settings` no banco
- Frontend detecta idioma do navegador se não houver localStorage
- Sync de preferências do servidor após login
- Se servidor não tem preferências, salva as locais como padrão

### Dropdown Dinâmico de Idiomas
- Novo endpoint `GET /api/admin/locales` escaneia arquivos de locale
- Arquivos de locale agora têm `meta.languageName` com nome nativo
- Frontend carrega idiomas do servidor e exibe em `<select>`
- Substitui botões hardcoded por dropdown dinâmico

### Configurações de Resumos IA
- Novo endpoint `GET /api/admin/languages` retorna lista de idiomas para resumos
- Novo endpoint `GET /api/admin/models` busca modelos da API Cerebras (com cache 30min)
- Preferências expandidas com `summary_language` e `cerebras_model`
- `cerebras.py` agora lê configurações do `app_settings` com fallback para `.env`
- Nova seção "Resumos IA" no modal de configurações (General tab)
- Dropdowns dinâmicos para idioma e modelo de IA
- Idiomas: 21 opções com nome nativo (inglês para prompt)
- Modelos: carregados da API Cerebras após login

### Seção Dados e Acordeões
- Aba General refatorada com acordeões colapsáveis (Alpine.js Collapse)
- Acordeões exclusivos: apenas um aberto por vez
- Nova seção "Dados" com configurações:
  - Intervalo de atualização dos feeds (minutos)
  - Máximo de posts por feed
  - Retenção de posts (dias)
  - Expiração de não lidos (dias)
- Preferências expandidas com `feed_update_interval`, `max_posts_per_feed`, `max_post_age_days`, `max_unread_days`
- Helpers no backend para outros módulos lerem configurações efetivas

### Seção Interface
- Nova seção "Interface" com configurações:
  - Duração das notificações (segundos, 0 para desativar)
  - Atualização automática (segundos de inatividade, 0 para desativar)
- Preferências expandidas com `toast_timeout_seconds`, `idle_refresh_seconds`
- Helpers `get_effective_toast_timeout` e `get_effective_idle_refresh` no backend

### Modo de Leitura Split View
- Novo modo de leitura estilo Gmail com tela dividida
- Opções: "Tela Cheia" (modal, padrão) ou "Dividido" (split view)
- Split view: lista de posts em cima, painel de leitura embaixo
- Proporção redimensionável: arrastar divisória para ajustar (20%-80%)
- Preferência `split_ratio` salva no servidor
- Apenas em desktop (≥1024px), mobile continua com modal
- Mesma funcionalidade: duas colunas (original + resumo IA), atalhos, etc.
- Toggle no Settings > Appearance > Modo de Leitura
- Preferência `reading_mode` salva no servidor

### Reorganização das Configurações
- "Modo de Leitura" movido de Interface para Appearance
- Seção "Interface" renomeada para "Outros"

---

## Sessão 2026-01-05 — Sync e Navegação

- API `/posts` agora retorna `feed_unread_counts` com counts atualizados dos feeds
- Frontend atualiza sidebar quando recebe posts (sincroniza counts)
- `setFilter()` agora rastreia posição para navegação `[`/`]` após cliques
- Fix: Navegação `]` após "marcar todos como lidos" agora funciona corretamente
- Novo estado `lastFeedNavIndex` para rastrear posição na navegação por feeds

---

## Sessão 2026-01-02/03 — i18n e UX

- Confirmação antes de "Marcar todos como lidos" (com contagem e contexto)
- Todas as strings traduzidas (toasts, erros do backend)
- Modal de confirmação customizado (blur, instantâneo, Enter/Escape)
- Spinner no modal durante operações longas (mark all, delete)
- Atalhos visíveis nos botões: (A) Mark all, (R) Refresh, (X) Select, (M) Mark read
- Barra de atalhos no rodapé: J/K navegar, [/] feeds, Enter abrir
- Novo atalho `A` para marcar todos como lidos
- Navegação `[`/`]` por Favoritos, Não lidos, Categorias e Feeds
- Enter em categoria colapsa/expande
- Itens colapsados não são navegáveis
- Cache busting: `APP_VERSION` em app.js, usado em CSS/JS/locales

---

## Sessão 2025-12-31 — UX

- Link GitHub no rodapé da sidebar
- Atalhos para seleção em lote: `X` modo, `Espaço` checkbox, `M` marcar lidos
- Descoberta automática de feeds (POST `/feeds/discover?url=`)

---

## Sessão 2025-12-29 — Estabilidade

- Prompts dinâmicos (`prompts.yaml` sem restart)
- Regras de script multilíngue (Latin, Cyrillic, Hanzi, etc.)
- Gunicorn com timeout e max-requests (previne travamentos)
- Backfill automático de resumos órfãos
- UI só recarrega se houver posts novos

---

## Migrações Alembic

| ID | Descrição |
|----|-----------|
| `172dd9c19d31` | Schema inicial |
| `28e3af40a708` | is_starred, starred_at |
| `73152e004d90` | translated_title em ai_summaries |

---

## Comandos Úteis

```bash
# Status dos serviços
sudo systemctl status rss-reader risos_israel risos_michael

# Logs
journalctl -u rss-reader -f

# Fila de resumos
sqlite3 backend/data/reader.db "SELECT COUNT(*) FROM summary_queue"

# Posts órfãos (sem resumo)
sqlite3 backend/data/reader.db "
SELECT COUNT(*) FROM posts p
WHERE p.content_hash IS NOT NULL
AND NOT EXISTS (SELECT 1 FROM ai_summaries a WHERE a.content_hash = p.content_hash)
AND NOT EXISTS (SELECT 1 FROM summary_queue q WHERE q.content_hash = p.content_hash)"

# Rodar migrações
cd backend && source venv/bin/activate && alembic upgrade head
```

---

## API Keys

```bash
# backend/.env - múltiplas keys separadas por vírgula
CEREBRAS_API_KEY=key1,key2,key3
```

Round-robin automático. Keys com 429 entram em cooldown de 60s.

---

## Backlog

- [ ] Busca de posts por título/conteúdo
- [ ] Tags/labels customizadas
- [ ] PWA com service worker
- [ ] Estatísticas de leitura

---

## Referências

- `README.md` — Documentação pública e features
- `PROJECT.md` — Especificação técnica (inglês)
- `AI.md` — Guia para desenvolvimento assistido por IA
- `PLANO.md` — Plano original de implementação
