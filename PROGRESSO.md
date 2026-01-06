# Progresso da Implementação — Risos

**Última atualização:** 2026-01-06
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

## Sessão 2026-01-06 — Preferências e Configurações

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
- `PROJETO.md` — Especificação técnica
- `PLANO.md` — Plano original de implementação
