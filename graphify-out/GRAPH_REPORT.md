# Graph Report - /Users/janiosarmento/projects/risos  (2026-05-13)

## Corpus Check
- 81 files · ~105,279 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 803 nodes · 1297 edges · 71 communities (44 shown, 27 thin omitted)
- Extraction: 76% EXTRACTED · 24% INFERRED · 0% AMBIGUOUS · INFERRED: 315 edges (avg confidence: 0.69)
- Token cost: 163,542 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_ORM Data Models|ORM Data Models]]
- [[_COMMUNITY_Cerebras AI Service|Cerebras AI Service]]
- [[_COMMUNITY_Pydantic Schemas|Pydantic Schemas]]
- [[_COMMUNITY_Feed Ingestion Pipeline|Feed Ingestion Pipeline]]
- [[_COMMUNITY_API Key Infrastructure|API Key Infrastructure]]
- [[_COMMUNITY_Scheduler & Cleanup|Scheduler & Cleanup]]
- [[_COMMUNITY_Feed & Category Routes|Feed & Category Routes]]
- [[_COMMUNITY_Post Routes|Post Routes]]
- [[_COMMUNITY_Suggestions & User Profile|Suggestions & User Profile]]
- [[_COMMUNITY_Database Base Layer|Database Base Layer]]
- [[_COMMUNITY_Preferences Routes|Preferences Routes]]
- [[_COMMUNITY_AI Client Core|AI Client Core]]
- [[_COMMUNITY_Proxy & App Entrypoint|Proxy & App Entrypoint]]
- [[_COMMUNITY_Tag Merge Scripts|Tag Merge Scripts]]
- [[_COMMUNITY_Content Processing|Content Processing]]
- [[_COMMUNITY_Frontend App Layer|Frontend App Layer]]
- [[_COMMUNITY_Prompts & Config|Prompts & Config]]
- [[_COMMUNITY_Suggestion Engine|Suggestion Engine]]
- [[_COMMUNITY_Content Extractor|Content Extractor]]
- [[_COMMUNITY_Tag Services & Scripts|Tag Services & Scripts]]
- [[_COMMUNITY_Category Routes|Category Routes]]
- [[_COMMUNITY_App Startup & Error Handling|App Startup & Error Handling]]
- [[_COMMUNITY_UI Store (ThemeFont)|UI Store (Theme/Font)]]
- [[_COMMUNITY_Branding & Icons|Branding & Icons]]
- [[_COMMUNITY_Ollama Fallback|Ollama Fallback]]
- [[_COMMUNITY_Blocked Terms Logic|Blocked Terms Logic]]
- [[_COMMUNITY_AI Circuit Breaker|AI Circuit Breaker]]
- [[_COMMUNITY_API Key Config|API Key Config]]
- [[_COMMUNITY_Post Export (MarkdownZIP)|Post Export (Markdown/ZIP)]]
- [[_COMMUNITY_AI Model Preferences|AI Model Preferences]]
- [[_COMMUNITY_Database Session|Database Session]]
- [[_COMMUNITY_Alembic Environment|Alembic Environment]]
- [[_COMMUNITY_Auth Dependency|Auth Dependency]]
- [[_COMMUNITY_App Lifecycle|App Lifecycle]]
- [[_COMMUNITY_Post Detail & Summary Status|Post Detail & Summary Status]]
- [[_COMMUNITY_Migration keep_unread|Migration: keep_unread]]
- [[_COMMUNITY_Migration initial schema|Migration: initial schema]]
- [[_COMMUNITY_Migration translated_title|Migration: translated_title]]
- [[_COMMUNITY_Migration starred columns|Migration: starred columns]]
- [[_COMMUNITY_Migration suggestions & tags|Migration: suggestions & tags]]
- [[_COMMUNITY_Migration topics|Migration: topics]]
- [[_COMMUNITY_Font Scale & UI Design|Font Scale & UI Design]]
- [[_COMMUNITY_TagSuggestion Services|Tag/Suggestion Services]]
- [[_COMMUNITY_Rate Limiter|Rate Limiter]]
- [[_COMMUNITY_Cerebras Constants|Cerebras Constants]]
- [[_COMMUNITY_Cerebras Package Init|Cerebras Package Init]]
- [[_COMMUNITY_Ollama Package Init|Ollama Package Init]]
- [[_COMMUNITY_Curation Component|Curation Component]]
- [[_COMMUNITY_Settings Component|Settings Component]]
- [[_COMMUNITY_Post Detail Component|Post Detail Component]]
- [[_COMMUNITY_Docker & Requirements|Docker & Requirements]]
- [[_COMMUNITY_Agent & Claude Config|Agent & Claude Config]]
- [[_COMMUNITY_Post Schemas|Post Schemas]]
- [[_COMMUNITY_Config Rationale|Config Rationale]]
- [[_COMMUNITY_User Schema|User Schema]]
- [[_COMMUNITY_Category Create Schema|Category Create Schema]]
- [[_COMMUNITY_Category Update Schema|Category Update Schema]]
- [[_COMMUNITY_Category Response Schema|Category Response Schema]]
- [[_COMMUNITY_Category Reorder Schema|Category Reorder Schema]]
- [[_COMMUNITY_Feed Create Schema|Feed Create Schema]]
- [[_COMMUNITY_Feed Update Schema|Feed Update Schema]]
- [[_COMMUNITY_Mark Read Schema|Mark Read Schema]]
- [[_COMMUNITY_Security Dependency|Security Dependency]]
- [[_COMMUNITY_Feed Ingestion Result|Feed Ingestion Result]]

## God Nodes (most connected - your core abstractions)
1. `Scheduler` - 25 edges
2. `Post` - 23 edges
3. `_get_setting()` - 18 edges
4. `Feed` - 17 edges
5. `PostTag` - 17 edges
6. `TopicTag` - 17 edges
7. `AppSettings` - 16 edges
8. `SummaryQueue` - 15 edges
9. `BatchUnstarRequest` - 15 edges
10. `CurateRequest` - 15 edges

## Surprising Connections (you probably didn't know these)
- `AGENTS.md — Agent Instructions` --semantically_similar_to--> `CLAUDE.md — Project Instructions for AI Agents`  [INFERRED] [semantically similar]
  AGENTS.md → CLAUDE.md
- `Tag Overlap Scoring (Suggestions System)` --references--> `Risos README (Public Documentation)`  [INFERRED]
  PLANO_SUGESTOES.md → README.md
- `PLANO_SUGESTOES.md — Suggestions System Implementation Plan` --references--> `Risos — RSS Reader with AI (Project Spec)`  [EXTRACTED]
  PLANO_SUGESTOES.md → PROJECT.md
- `Risos README (Public Documentation)` --references--> `PROMPTS.md — AI Prompts Reference`  [EXTRACTED]
  README.md → PROMPTS.md
- `Docker Compose — Risos Services` --references--> `backend/requirements.txt — Python Dependencies`  [INFERRED]
  docker-compose.yml → backend/requirements.txt

## Hyperedges (group relationships)
- **Risos Agent Instruction Files** — agents_md_risos, claude_md_risos [EXTRACTED 1.00]
- **Risos Core Documentation Set** — project_md_risos, readme_risos, ai_md_risos, progresso_md_risos [EXTRACTED 1.00]
- **Risos AI Configuration Files** — prompts_yaml_backend, prompts_md_risos, cerebras_circuit_breaker [INFERRED 0.85]
- **Risos Frontend Files** — index_html_risos, js_architecture_md, font_size_controls_spec [INFERRED 0.85]
- **App UI Screenshot Collection** — screenshot_main_screen, screenshot_settings, screenshot_post [INFERRED 0.95]
- **App Icon Asset Family** — icon_svg, icon_apple_touch, icon_192, icon_512, favicon_16, favicon_32 [INFERRED 0.95]
- **ORM Models (SQLAlchemy Base)** — models_category, models_feed, models_post, models_posttag, models_ignoredtag, models_aisummary, models_summaryqueue, models_summaryfailure, models_appsettings, models_tokenblacklist, models_schedulerlock, models_cleanuplog, models_topic, models_topictag [EXTRACTED 1.00]
- **FastAPI Routers registered on /api prefix** — routes_auth_router, routes_feeds_router, routes_posts_router, routes_categories_router, routes_proxy_router, routes_admin_router, routes_preferences_router, routes_suggestions_router, routes_tags_router, routes_topics_router [EXTRACTED 1.00]
- **AI Suggestion Pipeline (tags -> profile -> suggestions)** — models_posttag, models_ignoredtag, routes_tags_router, routes_suggestions_router, routes_preferences_get_effective_blocked_terms [INFERRED 0.85]
- **AI Summary Pipeline (queue -> AISummary -> posts)** — models_summaryqueue, models_aisummary, models_summaryfailure, routes_posts_regenerate_summary, routes_posts_get_summary_status, routes_admin_reset_circuit_breaker [INFERRED 0.85]
- **Effective Preference Getter Functions** — routes_preferences_get_effective_cerebras_model, routes_preferences_get_effective_summary_language, routes_preferences_get_effective_api_base_url, routes_preferences_get_effective_blocked_terms [EXTRACTED 1.00]

## Communities (71 total, 27 thin omitted)

### Community 0 - "ORM Data Models"
Cohesion: 0.06
Nodes (87): AISummary, AppSettings, Category, Feed, IgnoredTag, Post, PostTag, Database ORM models. Complete schema as per PROJETO.md (+79 more)

### Community 1 - "Cerebras AI Service"
Cohesion: 0.06
Nodes (44): call_llm_json(), _call_llm_json_locked(), _call_model(), _get_api_base_url(), get_available_models(), Cerebras client for AI summary generation. API calls, tag translation, model fal, Translate non-English tags to English using a fast, small model.     Returns tra, Make a single API call to a specific model and parse the response.      Raises: (+36 more)

### Community 2 - "Pydantic Schemas"
Cohesion: 0.05
Nodes (45): LoginResponse, Response do login com token JWT, Informações do usuário autenticado, UserInfo, clear_models_cache(), Clear the models cache and all model cooldowns., Settings, engine (+37 more)

### Community 3 - "Feed Ingestion Pipeline"
Cohesion: 0.07
Nodes (37): Exception, _check_duplicate_by_guid(), _check_duplicate_by_hash(), _check_duplicate_by_url(), FeedIngestionResult, _process_entry(), Feed ingestion service. Integrates parser, normalization, sanitization and dedup, Process a feed entry.      Returns:         Tuple of (created Post or None, erro (+29 more)

### Community 4 - "API Key Infrastructure"
Cohesion: 0.08
Nodes (18): ApiKeyRotator, CircuitBreaker, Infrastructure: API key rotation and circuit breaker for the Cerebras client., Put a key in cooldown after rate limit., Remove cooldown from a key., Check if any API key is available (not in cooldown).         Does NOT advance th, Return status of all keys., Circuit breaker to protect against API failures.      States:     - CLOSED: Norm (+10 more)

### Community 5 - "Scheduler & Cleanup"
Cohesion: 0.09
Nodes (17): CleanupLog, SchedulerLock, Scheduler for background jobs. Uses database lock to ensure only one active inst, Heartbeat loop to keep lock active., Update lock heartbeat., Start all background jobs., Job to update feeds periodically., Background jobs manager with distributed lock. (+9 more)

### Community 6 - "Feed & Category Routes"
Cohesion: 0.1
Nodes (27): FeedResponse, Category, Feed, create_feed(), delete_feed(), discover_feed(), enable_feed(), export_opml() (+19 more)

### Community 7 - "Post Routes"
Cohesion: 0.1
Nodes (25): batch_unstar(), get_full_content(), get_post_or_404(), is_safe_redirect_url(), mark_read_batch(), Post routes. Read, mark as read, content extraction and redirect., Fetch post by ID or raise 404., Toggle the skip_summary flag on a post. (+17 more)

### Community 8 - "Suggestions & User Profile"
Cohesion: 0.11
Nodes (23): AdminActionResponse, get_status(), Routes for the AI suggestion system. Includes status endpoint and admin controls, Response for suggestion system status., Response for admin actions., Get the current status of the suggestion system.     Shows whether the user has, Force regeneration of user interest profile.     Requires at least MIN_LIKED_POS, regenerate_profile() (+15 more)

### Community 9 - "Database Base Layer"
Cohesion: 0.13
Nodes (24): Base (SQLAlchemy DeclarativeBase), AISummary, CleanupLog, IgnoredTag, Post, PostTag, SchedulerLock, SummaryFailure (+16 more)

### Community 10 - "Preferences Routes"
Cohesion: 0.13
Nodes (21): get_effective_blocked_terms(), get_effective_feed_update_interval(), get_effective_idle_refresh(), get_effective_max_post_age_days(), get_effective_max_posts_per_feed(), get_effective_max_unread_days(), get_effective_model_cooldown(), get_effective_profile_min_tag_freq() (+13 more)

### Community 11 - "AI Client Core"
Cohesion: 0.14
Nodes (22): API Key Rotator, Cerebras API Client, Cerebras Constants, Cerebras Infrastructure, Cerebras Package Init, Cerebras Parsing, Cerebras Prompts, Cerebras Types (+14 more)

### Community 12 - "Proxy & App Entrypoint"
Cohesion: 0.11
Nodes (19): USER_AGENT, FastAPI app, limiter, admin router, auth router, categories router, feeds router, posts router (+11 more)

### Community 13 - "Tag Merge Scripts"
Cohesion: 0.19
Nodes (16): apply_merges_to_db(), build_cluster_prompt(), build_stem_clusters(), call_llm(), call_llm_with_retry(), call_ollama_json(), catch_all_ungrouped(), log() (+8 more)

### Community 14 - "Content Processing"
Cohesion: 0.12
Nodes (18): compute_content_hash(), normalize_for_hash(), Content hashing for deduplication. Normalizes content before computing hash., Normalize text for consistent hashing.      - Remove boilerplate     - Normalize, Compute SHA-256 hash of content + title + URL.      Args:         content: HTML, _add_link_attributes(), extract_text(), _filter_attributes() (+10 more)

### Community 15 - "Frontend App Layer"
Cohesion: 0.22
Nodes (20): Alembic Environment Configuration, app.js - Alpine.js Main Application, components/curation.js - Curation Mixin, components/postDetail.js - Post Detail Mixin, components/settings.js - Settings Mixin, index.html - Main SPA Entry Point, lib.py - Shared Script Utilities, Migration: Add keep_unread (c3d4e5f6g7h8) (+12 more)

### Community 16 - "Prompts & Config"
Cohesion: 0.14
Nodes (17): load_prompts(), Load prompts from prompts.yaml file., _get_popular_tags(), get_system_prompt(), get_user_prompt(), Prompt construction for the Cerebras client., Return the most frequent tags, cached in memory for 1 hour., Returns the system prompt from DB settings or prompts.yaml fallback. (+9 more)

### Community 17 - "Suggestion Engine"
Cohesion: 0.14
Nodes (17): get_effective_suggestion_min_tags(), get_effective_tags_per_post(), Get number of tags per post from app_settings or default (7)., Get minimum tag overlap for suggestions from app_settings or default (3)., process_suggestions(), Force processing of suggestion candidates.     Resets existing suggestions so th, clear_all_suggestions(), get_suggestion_candidates() (+9 more)

### Community 18 - "Content Extractor"
Cohesion: 0.16
Nodes (17): _clean_non_article_content(), _extract_from_html(), extract_full_content(), ExtractedContent, _fetch_with_curl_impersonate(), _is_cloudflare_blocked(), _is_curl_impersonate_available(), _is_non_article_content() (+9 more)

### Community 19 - "Tag Services & Scripts"
Cohesion: 0.15
Nodes (14): clear_rate_limits(), compute_content_hash(), log(), Process a list of posts in batches, with delay between API calls.      Returns:, Print with immediate flush for background execution., Reset circuit breaker timing and clear all key cooldowns., Regenerate summary and tags for a single post.      Args:         db: SQLAlchemy, regenerate_one() (+6 more)

### Community 20 - "Category Routes"
Cohesion: 0.17
Nodes (14): CategoryResponse, Response de categoria, create_category(), delete_category(), get_category(), list_categories(), Category routes. Full CRUD + reordering., Fetch a category by ID. (+6 more)

### Community 21 - "App Startup & Error Handling"
Cohesion: 0.19
Nodes (9): check_database_integrity(), lifespan(), Main FastAPI application. RSS Reader backend with AI., Reset all AI-related state on startup.     Clears circuit breaker, API key coold, Lifespan context manager for startup and shutdown.     Runs critical checks on s, Run Alembic migrations automatically.     Critical failure if unable to apply., Check SQLite database integrity.     - DB > 100MB: PRAGMA quick_check (faster), reset_ai_state() (+1 more)

### Community 22 - "UI Store (Theme/Font)"
Cohesion: 0.18
Nodes (3): applyFontScale(), decreaseFontScale(), increaseFontScale()

### Community 23 - "Branding & Icons"
Cohesion: 0.23
Nodes (13): Risos App Branding (RSS + Cat with Tears of Joy), Favicon 16px, Favicon 32px, PWA Icon 192px, PWA Icon 512px, Apple Touch Icon (180px), App Icon SVG Source, Main Screen Screenshot (+5 more)

### Community 24 - "Ollama Fallback"
Cohesion: 0.2
Nodes (11): generate_summary(), _generate_summary_locked(), Generate summary using Cerebras API with model fallback.      Tries the user's p, Inner implementation, called under _api_lock., is_garbage_content(), Detect if content is an error/session/paywall page     that should not be sent t, GarbageContentError, Content is garbage (error page, paywall, empty result).     Post should be marke (+3 more)

### Community 25 - "Blocked Terms Logic"
Cohesion: 0.2
Nodes (11): load_prompts, Check if a title matches a blocked term.      Without *: whole-word match ("ford, title_matches_term(), get_preferences(), _mask_keys(), Get user preferences.     Settings return env defaults if not overridden., Update user preferences.     Only updates fields that are provided (not None)., Remove suggestion status from posts matching blocked terms. (+3 more)

### Community 26 - "AI Circuit Breaker"
Cohesion: 0.24
Nodes (11): AI.md — Risos AI Developer Guide, Circuit Breaker Pattern (Cerebras AI), Content Deduplication Strategy (GUID → URL → Hash), PLANO_SUGESTOES.md — Suggestions System Implementation Plan, PROGRESSO.md — Development Progress Log, Risos — RSS Reader with AI (Project Spec), PROMPTS.md — AI Prompts Reference, backend/prompts.yaml — AI Prompt Templates (+3 more)

### Community 27 - "API Key Config"
Cohesion: 0.25
Nodes (5): Application configuration using pydantic-settings. Loads environment variables f, Application settings loaded from .env, Validate JWT_SECRET in __init__, Settings, BaseSettings

### Community 28 - "Post Export (Markdown/ZIP)"
Cohesion: 0.29
Nodes (8): export_selection(), export_starred(), _post_to_markdown(), Export selected posts as a ZIP of markdown files., Convert text to a safe filename slug., Convert a post to a markdown string., Export starred posts as a ZIP of markdown files., _slugify()

### Community 29 - "AI Model Preferences"
Cohesion: 0.29
Nodes (7): AppSettings, get_effective_api_base_url(), get_effective_cerebras_model(), get_effective_summary_language(), Get summary language from app_settings or env default., Get Cerebras model from app_settings or env default., Get API base URL from app_settings or default.

### Community 30 - "Database Session"
Cohesion: 0.33
Nodes (5): get_db(), SQLite database configuration with SQLAlchemy. WAL mode enabled for better concu, Configure SQLite PRAGMAs on connect:     - WAL mode for better concurrency     -, Dependency injection for FastAPI.     Provides a database session and ensures it, set_sqlite_pragma()

### Community 31 - "Alembic Environment"
Cohesion: 0.33
Nodes (5): Alembic environment configuration. Importa modelos da aplicação para autogenerat, Run migrations in 'offline' mode.     Gera SQL sem conectar ao banco., Run migrations in 'online' mode.     Conecta ao banco e executa migrations., run_migrations_offline(), run_migrations_online()

### Community 33 - "Auth Dependency"
Cohesion: 0.5
Nodes (3): get_current_user(), Dependencies for FastAPI injection. Includes JWT authentication., Validate JWT token and return user info.     Checks:     - Valid token     - Tok

### Community 34 - "App Lifecycle"
Cohesion: 0.5
Nodes (4): check_database_integrity, lifespan, reset_ai_state, run_migrations

### Community 35 - "Post Detail & Summary Status"
Cohesion: 0.5
Nodes (4): get_post(), get_summary_status(), Return AI summary status for a post., Fetch a post by ID with full content.     Includes AI summary if available.

### Community 42 - "Font Scale & UI Design"
Cohesion: 0.5
Nodes (4): Alpine.js Mixin Pattern (spread into app()), Font Scale Persistence via sessionStorage, Font Size Controls Design Spec (A- / A+), ARCHITECTURE.md — JavaScript Architecture

### Community 43 - "Tag/Suggestion Services"
Cohesion: 1.0
Nodes (3): Suggestions Service, Tags Service, User Profile Service

## Knowledge Gaps
- **328 isolated node(s):** `Application configuration using pydantic-settings. Loads environment variables f`, `Load prompts from prompts.yaml file.`, `Application settings loaded from .env`, `Returns list of API keys (supports comma-separated values).`, `Validate JWT_SECRET in __init__` (+323 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **27 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Post` connect `ORM Data Models` to `Feed Ingestion Pipeline`, `Scheduler & Cleanup`?**
  _High betweenness centrality (0.085) - this node is a cross-community bridge._
- **Why does `AppSettings` connect `ORM Data Models` to `Prompts & Config`, `Suggestions & User Profile`, `API Key Infrastructure`, `Scheduler & Cleanup`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Why does `Scheduler` connect `Scheduler & Cleanup` to `ORM Data Models`?**
  _High betweenness centrality (0.059) - this node is a cross-community bridge._
- **Are the 8 inferred relationships involving `Scheduler` (e.g. with `SchedulerLock` and `Feed`) actually correct?**
  _`Scheduler` has 8 INFERRED edges - model-reasoned connections that need verification._
- **Are the 21 inferred relationships involving `Post` (e.g. with `TagRequest` and `SuggestMergesRequest`) actually correct?**
  _`Post` has 21 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `Feed` (e.g. with `TagRequest` and `SuggestMergesRequest`) actually correct?**
  _`Feed` has 15 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Application configuration using pydantic-settings. Loads environment variables f`, `Load prompts from prompts.yaml file.`, `Application settings loaded from .env` to the rest of the system?**
  _328 weakly-connected nodes found - possible documentation gaps or missing edges._