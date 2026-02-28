# Progresso da Implementação — Risos

**Última atualização:** 2026-02-27
**Repositório:** https://github.com/janiosarmento/risos

---

## Estado Atual

Projeto em produção com IA (Cerebras), tradução automática de títulos, fallback de modelos, atribuição de modelo nos resumos, sugestões com score %, tags ignoradas para controlo granular, termos bloqueados para filtrar ruído, SVG sprite sheet, e múltiplas instâncias.

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

## Sessão 2026-02-27 — Termos Bloqueados, Cache Buster Unificado, Exportação de Favoritos

### Termos Bloqueados (Blocked Terms)
- Nova feature para reduzir ruído nos feeds: termos que marcam posts indesejados
- Termos armazenados em `app_settings` (chave `pref_blocked_terms`), newline-separated
- Backend computa `is_blocked` dinamicamente para cada post (LIKE case-insensitive no título)
- Suporte a wildcard `%` para padrões flexíveis (ex: `best % to watch`)
- Matching via Python `in` operator (equivalente a `LIKE '%term%'`)
- Borda vermelha à esquerda nos posts bloqueados (Tailwind classes dinâmicas)
- Botão "Mark all as read" transformado em split dropdown com opção "Mark blocked as read"
- Badge com contagem de bloqueados não lidos no dropdown
- Atalho de teclado `N` para marcar bloqueados como lidos
- Textarea nas Settings > Others para gerir termos (sort automático, dedup, lowercase)
- Traduções PT e EN

### Exportação de Favoritos como ZIP
- Novo endpoint `GET /api/posts/export-starred` gera ZIP com ficheiros `.md` individuais
- Cada post vira um markdown com título, título traduzido, feed, data, URL, sumário (uma linha + completo) e tags
- Nomes dos ficheiros: `titulo-normalizado-abc123.md` (slug + hash para evitar colisões)
- Agrupamento em subpastas por feed (vista global/categoria) ou flat (vista de feed individual)
- Aceita `feed_id` e `category_id` como filtros (segue o contexto da vista atual)
- Ícone de download junto ao botão "Favoritos", visível apenas com `starredCount > 0` e filtro ativo
- Novo ícone `#icon-download` na sprite sheet SVG
- ZIP gerado em memória com `zipfile` + `BytesIO` (stdlib, sem dependências novas)

### Cache Buster Unificado
- `APP_VERSION` definido uma única vez em `index.html` (inline `<script>`)
- CSS e JS carregados via `document.write` com o mesmo version
- `app.js` não define mais `APP_VERSION` — lê o global do HTML
- Apenas 1 ficheiro para atualizar em vez de 2-3

### Limpeza de Tags em Larga Escala (sessão anterior continuada)
- ~2.029 posts tiveram resumos apagados, ~14.899 tags apagadas
- Tags portuguesas removidas por padrões morfológicos (-ação, -mento, -dade, -ncia, etc.)
- ~97 posts marcados como lidos por título (tesla, smart home, 3d printer, etc.)
- Batch loop de regeneração em execução contínua (~100 posts/batch)

### Cache Buster
- Atualizado para `20260227f`

---

## Sessão 2026-02-26b — SVG Sprite Sheet, Skip Summary na Lista, Limpeza de Tags

### SVG Sprite Sheet (`<symbol>` + `<use>`)
- ~50 SVGs inline no `index.html` refactored para sprite sheet centralizado
- 23 `<symbol>` definitions num bloco `<svg class="hidden">` no início do `<body>`
- Cada SVG inline substituído por `<svg class="..."><use href="#icon-name"/></svg>`
- Star/Heart: toggle fill/stroke via `:fill`/`:stroke` dinâmicos do Alpine.js (em vez de dois `<path>` com `x-show`)
- Spinner, chevrons, check, x-close, refresh, external-link, prohibition, folder, rss, hamburger, lightbulb, settings, eye, eye-off, document, info, github, circle — todos centralizados

### Ícone de Skip Summary na Lista de Posts
- Posts marcados como `skip_summary` agora exibem ícone de proibição (⛔ SVG) antes do título na listagem
- `skip_summary` movido de `PostDetail` para `PostResponse` no schema (disponível na API de listagem)
- Campo `skip_summary` adicionado ao `post_dict` manual em `list_posts()` no `posts.py`

### Limpeza de Tags Problemáticas
- **Lote 1**: Tags `consumidor`, `direitos-digitais`, `economia`, `emprego`, `vagas` — 53 posts limpos (resumos + tags apagados)
- **Lote 2**: Tags `tecnologia`, `soberania-digital`, `guerra`, `tempo`, `tempo-real` — 205 posts limpos
- Posts limpos serão reprocessados nos próximos batches de regeneração

### Regeneração em Batch de Posts sem Tags
- Batches 7-13 executados nesta sessão (~700 posts processados)
- Batch loop automático implementado (corre lotes sequencialmente até acabar)
- Total acumulado: ~12.700 posts com tags, ~9.200 ainda por processar (de 26.300 total)
- Taxa de sucesso típica: ~90% OK, ~5% skipped, ~5% erros (rate limits)

### Cache Buster
- Atualizado para `20260226g` (múltiplas iterações: d→e→f→g)

---

## Sessão 2026-02-26 — Tags Ignoradas, Preferências no Servidor, Correcções

### Tags Ignoradas (Controlo Granular de Sugestões)
- Nova tabela `ignored_tags` para tags que o utilizador marca como irrelevantes
- API REST: `GET/POST/DELETE /api/tags/ignored`
- Novo router `routes/tags.py` registado em `main.py`
- Tags ignoradas excluídas de:
  - Geração de perfil (`user_profile.py`)
  - Scoring de sugestões (`suggestions.py` — subtraídas de ambos os lados: perfil e post)
- `ignored_tags` retornado no detalhe do post (`PostDetail.ignored_tags`)
- Ao ignorar/restaurar uma tag: sugestões são limpas e perfil invalidado

### Tags Clicáveis com Estados Visuais
- Tags sempre visíveis (removido toggle `showTags` / `PREF_SHOW_TAGS`)
- Renderização alterada de `x-html="renderTags()"` para `x-for` com tag chips
- 3 estados visuais:
  - **Purple/bold**: tag no perfil do utilizador (matched)
  - **Cinza**: tag neutra
  - **Riscada/cinza escuro**: tag ignorada
- Clique na tag alterna entre ignorada e não-ignorada
- Tooltips i18n para cada estado (PT e EN)
- Aplicado nos 2 modos: fullscreen e split view

### Preferências Migradas para Servidor
- `showTags` era a única setting em localStorage — migrada para `app_settings`
- Depois removida completamente (tags agora sempre visíveis)
- Todas as configurações agora persistem no servidor, sincronizadas entre dispositivos

### Regeneração em Batch de Posts sem Tags
- Batches 4-6 (300 posts): ~282 sucesso, ~16 skipped, ~2 erros

---

## Sessão 2026-02-26a — Correcção de Sugestões e Preferências

### Threshold Dinâmico de Sugestões
- Corrigido `get_effective_suggestion_min_tags()` que truncava valor para max=5 (hardcoded)
- Agora usa `tags_per_post` como limite superior dinâmico
- Slider de configuração no frontend usa `:max="tagsPerPost"` em vez de max="5"
- Descrições nas locales actualizadas para não mencionar "5" como máximo

### Limpar Sugestões ao Alterar Threshold
- Nova função `clear_all_suggestions()` — limpa todas as sugestões não lidas com um UPDATE
- Chamada automaticamente quando `suggestion_min_tags` é alterado nas preferências
- Eliminada duplicação: endpoint `process-suggestions` agora usa a mesma função
- Removida abordagem anterior (`revoke_suggestions_below_threshold`) que era complexa e falhava

### Correcção dos Selects nas Configurações
- Selects de modelo, idioma e locale não mostravam o valor salvo ao abrir Settings
- `:selected` em options de `x-for` não sincroniza correctamente após render
- Solução: `$nextTick` re-assign do valor após cada lista de opções carregar
- Afectados: `loadAvailableModels()`, `loadSummaryLanguages()`, `loadAvailableLocales()`

---

## Sessão 2026-02-25 — Refactoring Cerebras, Skip Summary, Tooltips

### Refactoring do Módulo Cerebras
- `cerebras.py` convertido em package `cerebras/` com ficheiros separados:
  - `_api.py` — geração de resumos, fallback de modelos
  - `_types.py` — `SummaryResult`, hierarquia de erros
  - `_infrastructure.py` — `CircuitBreaker`, `APIKeyRotator`
  - `_constants.py` — constantes partilhadas
  - `_prompts.py` — carregamento de prompts
  - `_legacy.py` — compatibilidade legada

### GarbageContentError
- Nova excepção centralizada para conteúdo sem qualidade (paywalls, error pages, respostas vazias)
- `generate_summary()` agora levanta `GarbageContentError` em vez de retornar `SummaryResult` vazio
- Simplificou 3 callers (scheduler, on-demand, regenerate_tagless) que verificavam resultados vazios

### Skip Summary
- Novo campo `skip_summary` (Boolean) no modelo Post
- Toggle manual via botão na UI (ícone 🚫, vermelho quando activo)
- Auto-skip em: falhas permanentes (5 tentativas), conteúdo sem qualidade, respostas vazias
- Scheduler e scripts ignoram posts com `skip_summary = True`
- Regenerar resumo bloqueado quando post está marcado como skip (toast de erro)
- ~4400 posts retroactivamente marcados como skip via queries SQL

### Tooltips i18n para Botões com Ícone
- Todos os botões com rótulo apenas ícone agora têm tooltips traduzidos
- Afectados: toggle de senha, menu mobile, categorias, split view, modal fullscreen, star, like, skip, regenerar
- Hardcoded strings em PT/EN substituídas por `:title="t('key')"`

### Remoção do Filtro de 24h nas Sugestões
- `CANDIDATE_WINDOW_HOURS = 24` removido — sugestões agora avaliam TODOS os posts não lidos
- Post com 6 tags sobrepostas (threshold 5) agora aparece correctamente como sugerido

### Tags Visíveis em Todos os Posts
- Tags do AI agora exibidas em todos os posts, não apenas nos sugeridos
- Tags que coincidem com o perfil do utilizador são destacadas

### Auto-tradução de Tags para Inglês
- Modelos não-GPT geravam tags em português; agora regra "All tags in lowercase English" adicionada ao fim do prompt

---

## Sessão 2026-02-24 — Limpeza de Interface, Economia de Tokens

### Auto-save e Remoção do Botão Save na Aba AI
- Settings AI agora salva automaticamente ao fechar o modal (como as outras abas)
- Botão "Save" removido da aba AI para interface mais limpa
- Estados `savingAiSettings`/`aiSettingsSaved` removidos do JS
- Label do reset clarificado: "Reset prompts to defaults" / "Restaurar prompts padrão"

### Resumos para Posts Favoritos Lidos
- Scheduler agora gera resumo para posts favoritos mesmo que já lidos
- Necessário para gerar tags adequadas para o sistema de sugestões
- Dois pontos ajustados: backfill (enfileiramento) e processamento da fila
- Condição: `is_read == False OR is_favorite == True`

---

## Sessão 2026-02-23 — Tags Configuráveis, Score de Sugestões, Atribuição de Modelo

### Tags por Post Configurável
- Novo placeholder `{tags_count}` no user prompt (substitui o "Exactly 7 tags" fixo)
- Setting "Tags per Post" (3-15, default 7) na aba AI das Settings
- Valor usado no prompt e como denominador do score de sugestões

### Score de Sugestões Significativo
- Fórmula alterada: `overlap / tags_per_post * 100` (antes era `overlap / total_profile_tags * 100`)
- Badge purple restaurado na lista de posts sugeridos com percentagem
- Regenerar sugestões agora reseta as existentes antes de re-calcular scores
- Corrigida condição JS que escondia badge quando score era 0 (falsy)

### Atribuição de Modelo nos Resumos
- Cada resumo gerado inclui `— nome_do_modelo` no final
- Aplicado nos 3 caminhos: scheduler, on-demand, e regeneração manual
- Campo `model` adicionado ao `SummaryResult`
- Nota: campo `model` da resposta da API Cerebras é não-fiável (devolve sempre `llama3.1-8b`); usa-se o modelo pedido

### Toggle de Senha no Login
- Botão de olho (show/hide) no campo de senha do login
- Estado local com `x-data="{ showPw: false }"`, sem poluir state global
- `tabindex="-1"` para não interferir na navegação por Tab
- Área de toque adequada para tablet/celular

### Cap de Tags Ajustado
- Truncação de tags subiu de 7 para 15 (máximo configurável de tags_per_post)

---

## Sessão 2026-02-21 — Fallback de Modelos, Prompt e Documentação

### Fallback Automático de Modelo IA
- Quando o modelo preferido retorna respostas inválidas, o sistema tenta outros modelos disponíveis
- Nova classe `ModelSpecificError` para erros de parsing/resposta (activa fallback)
- Erros de infraestrutura (429, 5xx, timeout) NÃO activam fallback
- Função `_call_model()` extraída para chamada individual a um modelo
- Função `get_available_models()` com cache de 30 minutos
- `generate_summary()` itera pela lista de modelos até obter sucesso

### Melhoria do Prompt de Resumos
- Regras anti-repetição adicionadas ao `prompts.yaml`
- Bullets devem adicionar informação nova (não repetir o parágrafo inicial)
- Resumo de uma linha não pode repetir a primeira frase do resumo longo
- Nova regra de verificação de qualidade antes de retornar

### Tradução de Títulos sem Conteúdo
- Posts sem conteúdo (comum no Lobsters, HN) agora usam o título como conteúdo
- Flag `title_only=True` ignora verificação `is_garbage_content()` (< 50 chars)
- Permite pelo menos traduzir o título mesmo sem resumo completo

### Botão de Reset do Circuit Breaker
- Novo endpoint `POST /api/admin/reset-circuit-breaker`
- Limpa estado do circuit breaker, cooldowns da fila e tentativas
- Link discreto "Resetar IA" / "Reset AI" no rodapé do modal de configurações

### Separadores de Data na Lista de Posts
- Separação visual quando a data relativa muda entre posts
- Classes CSS condicionais (border-top) baseadas em `getDateGroup()`
- Sem elemento HTML extra, apenas classes no artigo existente

### Correção da Exportação OPML
- `<a href>` não enviava token JWT → 404
- Substituído por `<button>` com `fetch()` autenticado + download via blob

### Rename "Todos os Posts" → "Não lidos"
- Label do sidebar corrigido para reflectir o comportamento real (filtro de não lidos)

### Atualização da Documentação
- README.md, AI.md, PROJECT.md e PROGRESSO.md actualizados

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
