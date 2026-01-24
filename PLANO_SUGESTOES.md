# Plano de Implementação — Posts Sugeridos

**Criado:** 2026-01-23
**Status:** Planejado (não iniciado)

---

## Visão Geral

Sistema de recomendação de posts baseado em IA. O usuário marca posts que "gostou" e o sistema sugere novos posts similares.

### Premissas

- ~500 posts novos/dia (feeds ativos como HN, Lobsters)
- Usar resumos já existentes (não processar posts sem resumo)
- Minimizar chamadas de IA (custo e rate limit)
- Cerebras não tem API de embeddings, então usamos tags + perfil textual

---

## Arquitetura

```
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Post com       │────▶│  Extração    │────▶│  post_tags      │
│  Resumo IA      │     │  de Tags     │     │  (até 10/post)  │
└─────────────────┘     └──────────────┘     └─────────────────┘
                                                      │
                                                      ▼
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Posts          │────▶│  Geração de  │────▶│  user_profile   │
│  "Gostados"     │     │  Perfil      │     │  (texto + tags) │
└─────────────────┘     └──────────────┘     └─────────────────┘
                                                      │
                                                      ▼
┌─────────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Posts Novos    │────▶│  Pré-filtro  │────▶│  Candidatos     │
│  (500/dia)      │     │  por Tags    │     │  (~30-50/dia)   │
└─────────────────┘     └──────────────┘     └─────────────────┘
                                                      │
                                                      ▼
                        ┌──────────────┐     ┌─────────────────┐
                        │  Comparação  │────▶│  Sugeridos      │
                        │  IA (batch)  │     │  (score ≥80%)   │
                        └──────────────┘     └─────────────────┘
```

---

## Fase 1: Schema e Migração

### 1.1 Nova Migração Alembic

```sql
-- Flag de "gostei" nos posts (separado de starred para não poluir favoritos)
ALTER TABLE posts ADD COLUMN is_liked INTEGER DEFAULT 0;
ALTER TABLE posts ADD COLUMN liked_at TEXT;

-- Tags extraídas dos posts
CREATE TABLE post_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(post_id, tag)
);
CREATE INDEX idx_post_tags_tag ON post_tags(tag);
CREATE INDEX idx_post_tags_post_id ON post_tags(post_id);

-- Sugestões
ALTER TABLE posts ADD COLUMN is_suggested INTEGER DEFAULT 0;
ALTER TABLE posts ADD COLUMN suggestion_score REAL;
ALTER TABLE posts ADD COLUMN suggested_at TEXT;

-- Perfil do usuário (em app_settings)
-- user_interest_profile TEXT - descrição textual dos interesses
-- user_interest_tags TEXT - JSON array das tags mais frequentes
-- user_profile_updated_at TEXT - quando foi atualizado
```

### 1.2 Modelos SQLAlchemy

```python
# models.py

class PostTag(Base):
    __tablename__ = "post_tags"

    id = Column(Integer, primary_key=True)
    post_id = Column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False)
    tag = Column(String, nullable=False)
    created_at = Column(String, default=lambda: datetime.utcnow().isoformat())

    post = relationship("Post", back_populates="tags")

    __table_args__ = (UniqueConstraint("post_id", "tag"),)

# Adicionar ao Post existente:
# is_liked = Column(Integer, default=0)
# liked_at = Column(String)
# is_suggested = Column(Integer, default=0)
# suggestion_score = Column(Float)
# suggested_at = Column(String)
# tags = relationship("PostTag", back_populates="post", cascade="all, delete-orphan")
```

---

## Fase 2: Extração de Tags

### 2.1 Modificar Prompt de Resumo

Atualizar `prompts.yaml` para incluir extração de tags:

```yaml
system_prompt: |
  You are a summarization assistant. Given an article, provide:
  1. A 2-3 sentence summary in {language}
  2. A one-line summary (max 100 chars) in {language}
  3. The title translated to {language} (or original if already in {language})
  4. 5-10 lowercase tags describing the main topics (in English)

  Respond in JSON format:
  {
    "summary": "...",
    "one_line": "...",
    "translated_title": "...",
    "tags": ["tag1", "tag2", ..., "tag10"]
  }
```

### 2.2 Modificar cerebras.py

```python
@dataclass
class SummaryResult:
    summary_pt: str
    one_line_summary: str
    translated_title: Optional[str]
    tags: List[str]  # Novo campo

def generate_summary(content: str) -> SummaryResult:
    # ... chamada existente ...

    # Parse da resposta
    result = json.loads(response)
    return SummaryResult(
        summary_pt=result["summary"],
        one_line_summary=result["one_line"],
        translated_title=result.get("translated_title"),
        tags=result.get("tags", []),
    )
```

### 2.3 Salvar Tags no Banco

Modificar o fluxo de salvamento de resumo para também criar entradas em `post_tags`.

```python
# Em routes/posts.py ou services/summary_processor.py

def save_summary_with_tags(db, post_id, summary_result):
    # Salvar resumo (já existente)
    save_ai_summary(db, content_hash, summary_result)

    # Salvar tags
    for tag in summary_result.tags:
        tag_normalized = tag.lower().strip()
        if tag_normalized:
            db.merge(PostTag(post_id=post_id, tag=tag_normalized))
    db.commit()
```

---

## Fase 3: Sistema de "Gostei"

### 3.1 Endpoint de Toggle

```python
# routes/posts.py

@router.patch("/{post_id}/like")
def toggle_like(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(404, "Post not found")

    post.is_liked = not post.is_liked
    post.liked_at = datetime.utcnow().isoformat() if post.is_liked else None
    db.commit()

    # Se mudou, invalidar perfil (será regenerado)
    invalidate_user_profile(db)

    return {"is_liked": post.is_liked, "liked_at": post.liked_at}
```

### 3.2 Auto-like ao Favoritar

Quando um post é favoritado (starred), automaticamente recebe like também:

```python
# routes/posts.py - modificar toggle_star existente

@router.patch("/{post_id}/star")
def toggle_star(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(404, "Post not found")

    post.is_starred = not post.is_starred
    post.starred_at = datetime.utcnow().isoformat() if post.is_starred else None

    # Auto-like ao favoritar (mas não remove like ao desfavoritar)
    if post.is_starred and not post.is_liked:
        post.is_liked = True
        post.liked_at = datetime.utcnow().isoformat()
        invalidate_user_profile(db)

    db.commit()
    return {"is_starred": post.is_starred, "starred_at": post.starred_at}
```

**Nota:** Desfavoritar NÃO remove o like. O usuário pode querer manter o like para treinar a IA mesmo sem guardar nos favoritos.

### 3.3 Frontend

- Novo ícone de "like" (coração ou polegar) no post
- Atalho de teclado: `L` para toggle like
- Contagem de posts gostados na UI (opcional)
- Ao favoritar, ícone de like também fica ativo automaticamente

---

## Fase 4: Geração de Perfil

### 4.1 Prompt de Geração de Perfil

```yaml
profile_prompt: |
  Based on these article summaries that the user liked, create:
  1. A brief description (2-3 sentences) of their interests
  2. A list of 10-15 key topic tags

  Summaries:
  {summaries}

  Respond in JSON:
  {
    "profile": "The user is interested in...",
    "tags": ["tag1", "tag2", ...]
  }
```

### 4.2 Serviço de Geração de Perfil

```python
# services/user_profile.py

def generate_user_profile(db: Session) -> dict:
    """Gera perfil baseado nos posts gostados."""

    liked_posts = db.query(Post).join(AISummary).filter(
        Post.is_liked == True
    ).order_by(Post.liked_at.desc()).limit(50).all()

    if len(liked_posts) < 10:
        return None  # Não gerar perfil ainda

    # Concatenar resumos
    summaries = "\n---\n".join([
        f"Title: {p.title}\nSummary: {p.ai_summary.summary_pt}"
        for p in liked_posts
    ])

    # Chamada IA
    result = call_cerebras(profile_prompt.format(summaries=summaries))

    # Salvar em app_settings
    set_setting(db, "user_interest_profile", result["profile"])
    set_setting(db, "user_interest_tags", json.dumps(result["tags"]))
    set_setting(db, "user_profile_updated_at", datetime.utcnow().isoformat())

    return result

def invalidate_user_profile(db: Session):
    """Marca perfil para regeneração."""
    set_setting(db, "user_profile_stale", "1")
```

### 4.3 Job de Atualização de Perfil

```python
# services/scheduler.py

@scheduler.scheduled_job('interval', hours=6)
def update_user_profile_if_needed():
    """Regenera perfil se estiver stale."""
    db = get_db_session()

    if get_setting(db, "user_profile_stale") == "1":
        generate_user_profile(db)
        set_setting(db, "user_profile_stale", "0")
```

---

## Fase 5: Pré-filtro por Tags

### 5.1 Identificar Candidatos

```python
# services/suggestions.py

def get_suggestion_candidates(db: Session) -> List[Post]:
    """
    Retorna posts novos que têm tags em comum com o perfil.
    Executado em batch (1x por hora ou após refresh de feeds).
    """

    # Tags do perfil do usuário
    profile_tags = json.loads(get_setting(db, "user_interest_tags") or "[]")
    if not profile_tags:
        return []

    # Posts das últimas 24h, com resumo, não sugeridos ainda, não lidos
    recent_posts = db.query(Post).join(AISummary).filter(
        Post.fetched_at > datetime.utcnow() - timedelta(hours=24),
        Post.is_suggested == 0,
        Post.is_read == 0,
    ).all()

    candidates = []
    for post in recent_posts:
        post_tags = {t.tag for t in post.tags}
        common_tags = post_tags.intersection(set(profile_tags))

        # Precisa de pelo menos 4 tags em comum
        if len(common_tags) >= 4:
            candidates.append((post, len(common_tags)))

    # Ordenar por mais tags em comum
    candidates.sort(key=lambda x: x[1], reverse=True)

    # Limitar a 50 candidatos por batch
    return [c[0] for c in candidates[:50]]
```

---

## Fase 6: Comparação IA em Batch

### 6.1 Prompt de Comparação

```yaml
comparison_prompt: |
  User interest profile:
  {profile}

  Rate how well each article summary matches the user's interests.
  Score from 0 to 100 (100 = perfect match).
  Only return articles with score >= 80.

  Articles:
  {articles}

  Respond in JSON:
  {
    "matches": [
      {"id": 123, "score": 85},
      {"id": 456, "score": 92}
    ]
  }
```

### 6.2 Serviço de Comparação

```python
# services/suggestions.py

def process_suggestion_candidates(db: Session):
    """
    Processa candidatos em batch e marca os aprovados como sugeridos.
    """

    profile = get_setting(db, "user_interest_profile")
    if not profile:
        return

    candidates = get_suggestion_candidates(db)
    if not candidates:
        return

    # Formatar artigos para o prompt
    articles = "\n---\n".join([
        f"ID: {p.id}\nTitle: {p.title}\nSummary: {p.ai_summary.one_line_summary}"
        for p in candidates
    ])

    # Chamada IA única para todo o batch
    result = call_cerebras(comparison_prompt.format(
        profile=profile,
        articles=articles
    ))

    # Marcar sugeridos
    for match in result.get("matches", []):
        post = db.query(Post).filter(Post.id == match["id"]).first()
        if post:
            post.is_suggested = 1
            post.suggestion_score = match["score"]
            post.suggested_at = datetime.utcnow().isoformat()

    db.commit()
```

### 6.3 Job de Processamento

```python
# services/scheduler.py

@scheduler.scheduled_job('interval', hours=1)
def process_suggestions():
    """Processa candidatos a sugestão a cada hora."""
    db = get_db_session()

    # Só processar se tiver perfil
    if get_setting(db, "user_interest_profile"):
        process_suggestion_candidates(db)
```

---

## Fase 7: Frontend

### 7.1 Seção na Sidebar

```html
<!-- Após "Não lidos", antes das categorias -->
<div x-show="suggestedCount > 0" class="p-2 border-b">
    <button
        @click="setFilter('suggested')"
        class="w-full text-left px-3 py-2 rounded text-sm flex items-center gap-2"
        :class="filter === 'suggested' ? 'bg-purple-600 text-white' : 'hover:bg-gray-200'"
    >
        <svg><!-- ícone de lâmpada ou estrela --></svg>
        <span>Sugeridos</span>
        <span class="ml-auto" x-text="suggestedCount"></span>
    </button>
</div>
```

### 7.2 Botão de Like no Post

```html
<!-- No header do post, ao lado do botão de star -->
<button
    @click="toggleLike(post)"
    :class="post.is_liked ? 'text-red-500' : 'text-gray-400'"
    title="Gostei"
>
    <svg><!-- ícone de coração --></svg>
</button>
```

### 7.3 Indicador de Sugestão

```html
<!-- Badge no card do post -->
<span
    x-show="post.is_suggested"
    class="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded"
>
    Sugerido ({{ post.suggestion_score }}%)
</span>
```

### 7.4 Atalhos de Teclado

- `L`: Toggle like no post atual
- `G S`: Ir para Sugeridos (go to suggested)

---

## Fase 8: API Endpoints

### Novos Endpoints

```python
# Listar posts sugeridos
GET /api/posts?suggested_only=true

# Toggle like
PATCH /api/posts/{id}/like

# Status do sistema de sugestões
GET /api/suggestions/status
# Retorna: {
#   "liked_count": 25,
#   "profile_ready": true,
#   "suggested_count": 12,
#   "last_processed": "2026-01-23T10:00:00Z"
# }

# Forçar regeneração de perfil (admin)
POST /api/admin/regenerate-profile

# Forçar processamento de sugestões (admin)
POST /api/admin/process-suggestions
```

---

## Estimativa de Custos

### Chamadas IA por Dia

| Operação | Frequência | Chamadas |
|----------|------------|----------|
| Resumos (já existente) | 500 posts | 500 |
| Extração de tags | junto com resumo | 0 extra |
| Atualização de perfil | 1x/semana | ~0.14 |
| Comparação em batch | 1-2x/dia | 2 |
| **Total extra** | | **~2/dia** |

### Armazenamento

- ~5 tags por post × 500 posts/dia = 2500 linhas/dia em post_tags
- ~75KB/dia de tags
- Negligível

---

## Ordem de Implementação

1. **Fase 1**: Schema e migração (30 min)
2. **Fase 2**: Extração de tags no resumo (1h)
3. **Fase 3**: Sistema de like (1h)
4. **Fase 7.2**: Botão de like no frontend (30 min)
5. **Testar e acumular likes** (esperar usuário gostar de 10+ posts)
6. **Fase 4**: Geração de perfil (1h)
7. **Fase 5**: Pré-filtro por tags (1h)
8. **Fase 6**: Comparação em batch (1h)
9. **Fase 7**: Frontend completo (2h)
10. **Fase 8**: Endpoints e admin (1h)

**Tempo total estimado:** 8-10 horas

---

## Decisões Tomadas

1. **Campo de liked**: Criar campo separado `is_liked` (não reusar `starred`)
   - Semântica diferente: favorito é para guardar, like é para treinar IA

2. **Auto-like ao favoritar**: Sim
   - Favoritar automaticamente marca como liked
   - Desfavoritar NÃO remove o like

3. **Quantidade de tags**: ⚠️ EM ANÁLISE (5-10 tags por post)
   - Mais tags = melhor matching, mas mais tokens consumidos
   - Avaliar custo/benefício antes de implementar

4. **Threshold de tags para candidato**: 4 tags em comum
   - Mais restritivo para melhorar qualidade das sugestões

5. **Score mínimo para sugestão**: 80%
   - Ajustar baseado em feedback se necessário

6. **Expiração de sugestões**: Não expira
   - Processos de limpeza existentes já removem posts antigos
   - Sugestões são removidas junto com os posts

---

## Referências

- [Cerebras API Docs](https://inference-docs.cerebras.ai/)
- [Sentence Transformers](https://www.sbert.net/) (alternativa futura com embeddings locais)
- `PROJECT.md` — Arquitetura geral do sistema
