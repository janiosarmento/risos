/**
 * Risos - Alpine.js Application
 */

// APP_VERSION is defined in index.html (single source of truth for cache busting)
const API_BASE = '/api';
const CURATION_WARN_THRESHOLD = 50; // Posts beyond this trigger a confirmation before AI curation

function app() {
    return {
        // Post detail: viewing, navigation, summary, export (from postDetail.js)
        ...postDetailMixin,
        // Settings: panel, CRUD, AI, tag merge, topics, prefs (from settings.js)
        ...settingsMixin,
        // Curation: AI curation, batch ops, export (from curation.js)
        ...curationMixin,

        // App info
        appVersion: APP_VERSION,

        // Authentication (cookie-based, no token management)
        get authenticated() { return Alpine.store('auth').authenticated; },
        set authenticated(v) { Alpine.store('auth').authenticated = v; },
        password: '',
        logging: false,
        loginError: null,

        // Data
        feeds: [],
        categories: [],
        posts: [],

        // UI State
        filter: 'unread',
        filterId: null,
        loading: false,
        refreshing: false,
        refreshingFeed: false,
        selectedIndex: -1,
        hasMore: true,
        offset: 0,
        pageSize: 50,
        postFilter: 'unread', // 'unread', 'all', or 'starred'
        selectedPosts: new Set(),
        selectMode: false,
        collapsedCategories: new Set(JSON.parse(localStorage.getItem('rss_collapsed_categories') || '[]')),
        sidebarOpen: false,
        desktopSidebarOpen: localStorage.getItem('rss_sidebar_open') !== '0',
        dragFeedId: null,
        dragOverCategoryId: null,
        lastNavMode: 'posts', // 'posts' (J/K) or 'sidebar' ([/])
        lastFeedNavIndex: 0, // Last position in feed navigation (for [/])
        tagFilter: null, // Current tag filter (composable with feed/category)
        tagFilterCount: 0, // Total posts matching current tag filter
        popularTags: [], // [{tag, count}] loaded from /api/tags/popular
        topTagsExpanded: localStorage.getItem('rss_top_tags_expanded') === '1', // Sidebar "Top Tags" section
        topics: [], // [{id, name, tags, post_count, unread_count}]
        selectedTopicId: null, // Currently active topic filter
        topicsExpanded: localStorage.getItem('rss_topics_expanded') === '1', // Sidebar "Topics" section
        searchQuery: '',
        _searchTimeout: null,
        _pendingReload: false,  // Reagendar loadPosts quando chamado durante outro load
        _pendingOpenPost: null, // Post para abrir no split view após navegação por feed
        // Health
        healthWarning: null,

        // Idle detection
        idleTimeoutId: null,
        get idleRefreshSeconds() { return Alpine.store('prefs').idleRefreshSeconds; },
        set idleRefreshSeconds(v) { Alpine.store('prefs').idleRefreshSeconds = v; },

        // Suggestions
        regeneratingSuggestions: false,
        get suggestionMinTags() { return Alpine.store('prefs').suggestionMinTags; },
        set suggestionMinTags(v) { Alpine.store('prefs').suggestionMinTags = v; },
        get profileMinTagFreq() { return Alpine.store('prefs').profileMinTagFreq; },
        set profileMinTagFreq(v) { Alpine.store('prefs').profileMinTagFreq = v; },
        get suggestionMinSummaryLength() { return Alpine.store('prefs').suggestionMinSummaryLength; },
        set suggestionMinSummaryLength(v) { Alpine.store('prefs').suggestionMinSummaryLength = v; },
        ignoredTags: new Set(), // Tags ignored for suggestions (loaded from server)
        get blockedTerms() { return Alpine.store('prefs').blockedTerms; },
        set blockedTerms(v) { Alpine.store('prefs').blockedTerms = v; },

        // Reading mode
        get readingMode() { return Alpine.store('prefs').readingMode; },
        set readingMode(v) { Alpine.store('prefs').readingMode = v; },
        get splitRatio() { return Alpine.store('prefs').splitRatio; },
        set splitRatio(v) { Alpine.store('prefs').splitRatio = v; },
        get feedReverseOrder() { return Alpine.store('prefs').feedReverseOrder; },
        set feedReverseOrder(v) { Alpine.store('prefs').feedReverseOrder = v; },
        get splitPaneStyle() { return this.isSplitMode ? `height: ${this.splitRatio}%` : ''; },

        // UI state (delegates to Alpine.store('ui'))
        get toast() { return Alpine.store('ui').toast; },
        get confirmModal() { return Alpine.store('ui').confirmModal; },
        get toastTimeoutSeconds() { return Alpine.store('prefs').toastTimeoutSeconds; },
        set toastTimeoutSeconds(v) { Alpine.store('prefs').toastTimeoutSeconds = v; },

        // I18n (delegates to Alpine.store('i18n'))
        get locale() { return Alpine.store('i18n').locale; },
        set locale(v) { Alpine.store('i18n').locale = v; },
        get translations() { return Alpine.store('i18n').translations; },
        get availableLocales() { return Alpine.store('i18n').availableLocales; },

        // Theme (delegates to Alpine.store('ui'))
        get theme() { return Alpine.store('ui').theme; },
        set theme(v) { Alpine.store('ui').theme = v; },
        get availableThemes() { return Alpine.store('ui').availableThemes; },

        // Preferences (delegates to Alpine.store('prefs'))
        get summaryLanguage() { return Alpine.store('prefs').summaryLanguage; },
        set summaryLanguage(v) { Alpine.store('prefs').summaryLanguage = v; },
        get aiModel() { return Alpine.store('prefs').aiModel; },
        set aiModel(v) { Alpine.store('prefs').aiModel = v; },
        get aiTimeout() { return Alpine.store('prefs').aiTimeout; },
        set aiTimeout(v) { Alpine.store('prefs').aiTimeout = v; },
        get aiMaxTokens() { return Alpine.store('prefs').aiMaxTokens; },
        set aiMaxTokens(v) { Alpine.store('prefs').aiMaxTokens = v; },
        get summaryTemperature() { return Alpine.store('prefs').summaryTemperature; },
        set summaryTemperature(v) { Alpine.store('prefs').summaryTemperature = v; },
        get summaryPresencePenalty() { return Alpine.store('prefs').summaryPresencePenalty; },
        set summaryPresencePenalty(v) { Alpine.store('prefs').summaryPresencePenalty = v; },
        get curationEngine() { return Alpine.store('prefs').curationEngine; },
        set curationEngine(v) { Alpine.store('prefs').curationEngine = v; },
        get availableSummaryLanguages() { return Alpine.store('prefs').availableSummaryLanguages; },
        set availableSummaryLanguages(v) { Alpine.store('prefs').availableSummaryLanguages = v; },
        get availableModels() { return Alpine.store('prefs').availableModels; },
        set availableModels(v) { Alpine.store('prefs').availableModels = v; },
        get janoSecretName() { return Alpine.store('prefs').janoSecretName; },
        set janoSecretName(v) { Alpine.store('prefs').janoSecretName = v; },
        get apiBaseUrl() { return Alpine.store('prefs').apiBaseUrl; },
        set apiBaseUrl(v) { Alpine.store('prefs').apiBaseUrl = v; },
        get backgroundJanoSecretName() { return Alpine.store('prefs').backgroundJanoSecretName; },
        set backgroundJanoSecretName(v) { Alpine.store('prefs').backgroundJanoSecretName = v; },
        get backgroundApiBaseUrl() { return Alpine.store('prefs').backgroundApiBaseUrl; },
        set backgroundApiBaseUrl(v) { Alpine.store('prefs').backgroundApiBaseUrl = v; },
        get backgroundAiModel() { return Alpine.store('prefs').backgroundAiModel; },
        set backgroundAiModel(v) { Alpine.store('prefs').backgroundAiModel = v; },
        get backgroundAvailableModels() { return Alpine.store('prefs').backgroundAvailableModels; },
        set backgroundAvailableModels(v) { Alpine.store('prefs').backgroundAvailableModels = v; },
        get systemPrompt() { return Alpine.store('prefs').systemPrompt; },
        set systemPrompt(v) { Alpine.store('prefs').systemPrompt = v; },
        get userPrompt() { return Alpine.store('prefs').userPrompt; },
        set userPrompt(v) { Alpine.store('prefs').userPrompt = v; },
        get defaultSystemPrompt() { return Alpine.store('prefs').defaultSystemPrompt; },
        set defaultSystemPrompt(v) { Alpine.store('prefs').defaultSystemPrompt = v; },
        get defaultUserPrompt() { return Alpine.store('prefs').defaultUserPrompt; },
        set defaultUserPrompt(v) { Alpine.store('prefs').defaultUserPrompt = v; },
        get tagsPerPost() { return Alpine.store('prefs').tagsPerPost; },
        set tagsPerPost(v) { Alpine.store('prefs').tagsPerPost = v; },
        get feedUpdateInterval() { return Alpine.store('prefs').feedUpdateInterval; },
        set feedUpdateInterval(v) { Alpine.store('prefs').feedUpdateInterval = v; },
        get maxPostAgeDays() { return Alpine.store('prefs').maxPostAgeDays; },
        set maxPostAgeDays(v) { Alpine.store('prefs').maxPostAgeDays = v; },
        get maxUnreadDays() { return Alpine.store('prefs').maxUnreadDays; },
        set maxUnreadDays(v) { Alpine.store('prefs').maxUnreadDays = v; },

        // Computed
        get totalUnread() {
            return this.feeds.reduce((sum, f) => sum + (f.unread_count || 0), 0);
        },

        get isSplitMode() {
            // Split mode when sidebar is visible (md: >=768px)
            return this.readingMode === 'split' && window.innerWidth >= 768;
        },

        starredCount: 0,
        suggestedCount: 0,

        // Post lookup helpers
        getPostIndex(id) {
            return this.posts.findIndex(p => p.id === id);
        },

        updatePost(id, updates) {
            // Find the post in the list and update it
            const index = this.getPostIndex(id);
            if (index >= 0) {
                // Replace the object to ensure Alpine reactivity on all browsers
                this.posts[index] = { ...this.posts[index], ...updates };
            }
            // Also update currentPost if it's the same post
            if (this.currentPost?.id === id) {
                this.currentPost = { ...this.currentPost, ...updates };
            }
        },

        isKey(e, key) {
            return e.key.toLowerCase() === key.toLowerCase();
        },

        // I18n wrappers (delegate to I18nStore — keeps HTML using t() unchanged)
        t(key, fallback = null) { return Alpine.store('i18n').t(key, fallback); },
        async loadLocale(locale) { return Alpine.store('i18n').loadLocale(locale); },

        // Render markdown to HTML. Output is untrusted (LLM-generated from
        // feed content, which may itself be attacker-controlled), so it is
        // always run through DOMPurify before being used with x-html.
        renderMarkdown(text) {
            if (!text) return '';
            let html;
            if (typeof marked !== 'undefined') {
                // Configure marked for safe rendering
                marked.setOptions({
                    breaks: true,  // Convert \n to <br>
                    gfm: true,     // GitHub Flavored Markdown
                });
                html = marked.parse(text);
            } else {
                // Fallback: basic conversion if marked not loaded
                html = text
                    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                    .replace(/\*(.+?)\*/g, '<em>$1</em>')
                    .replace(/^• /gm, '<li>')
                    .replace(/\n/g, '<br>');
            }
            if (typeof DOMPurify !== 'undefined') {
                return DOMPurify.sanitize(html);
            }
            // DOMPurify failed to load — fail closed to plain text rather
            // than risk injecting unsanitized HTML.
            return this._escHtml(text);
        },

        // Filter posts by tag (composable with feed/category)
        filterByTag(tag) {
            const normalized = tag.toLowerCase();
            if (this.tagFilter === normalized) {
                this.tagFilter = null;
            } else {
                this.tagFilter = normalized;
                this.selectedTopicId = null; // Mutually exclusive with topic filter
            }
            this.clearCuration();
            this.loadPosts(true);
        },

        // Clear the active tag filter
        clearTagFilter() {
            this.tagFilter = null;
            this.loadPosts(true);
        },

        // Toggle Top Tags sidebar section and load on first expand
        async toggleTopTags() {
            this.topTagsExpanded = !this.topTagsExpanded;
            localStorage.setItem('rss_top_tags_expanded', this.topTagsExpanded ? '1' : '0');
            if (this.topTagsExpanded && this.popularTags.length === 0) {
                await this.loadPopularTags();
            }
        },

        // Toggle sidebar visibility (desktop only, persisted)
        toggleDesktopSidebar() {
            this.desktopSidebarOpen = !this.desktopSidebarOpen;
            localStorage.setItem('rss_sidebar_open', this.desktopSidebarOpen ? '1' : '0');
        },

        // Load popular tags scoped to current context
        async loadPopularTags() {
            if (!this.topTagsExpanded) return;
            // Hide tags during search
            if (this.searchQuery.trim()) {
                this.popularTags = [];
                return;
            }
            this.popularTags = [];
            try {
                const params = new URLSearchParams({ limit: '10' });

                // Scope: feed or category
                if (this.filter === 'feed') {
                    params.set('feed_id', this.filterId);
                } else if (this.filter === 'category') {
                    params.set('category_id', this.filterId);
                }

                // Scope: topic
                if (this.selectedTopicId) {
                    params.set('topic_id', this.selectedTopicId);
                }

                // Scope: unread/starred/suggested
                if (this.filter === 'starred' || this.postFilter === 'starred') {
                    params.set('starred_only', 'true');
                } else if (this.filter === 'suggested') {
                    params.set('suggested_only', 'true');
                    if (this.postFilter === 'unread') {
                        params.set('unread_only', 'true');
                    }
                } else if (this.postFilter === 'unread') {
                    params.set('unread_only', 'true');
                }

                const data = await this.fetchApi(`/tags/popular?${params}`);
                this.popularTags = data.tags || [];
            } catch (e) {
                console.warn('Failed to load popular tags:', e);
            }
        },

        // Toggle Topics sidebar section and load on first expand
        async toggleTopics() {
            this.topicsExpanded = !this.topicsExpanded;
            localStorage.setItem('rss_topics_expanded', this.topicsExpanded ? '1' : '0');
            if (this.topicsExpanded && this.topics.length === 0) {
                await this.loadTopics();
            }
        },

        // Load topics from server.
        // Deduped: concurrent callers share the in-flight request instead of
        // each spawning another (expensive) /topics query on the backend.
        _topicsInflight: null,
        loadTopics() {
            if (this._topicsInflight) return this._topicsInflight;
            this._topicsInflight = (async () => {
                try {
                    const data = await this.fetchApi('/topics');
                    this.topics = data || [];
                } catch (e) {
                    console.warn('Failed to load topics:', e);
                } finally {
                    this._topicsInflight = null;
                }
            })();
            return this._topicsInflight;
        },

        // Debounced topic refresh. Bursts of actions (marking a run of posts
        // read, bulk ops, periodic timers) collapse into a single request.
        _topicsRefreshTimer: null,
        scheduleTopicsRefresh(delay = 1500) {
            if (!this.topicsExpanded) return;
            if (this._topicsRefreshTimer) clearTimeout(this._topicsRefreshTimer);
            this._topicsRefreshTimer = setTimeout(() => {
                this._topicsRefreshTimer = null;
                this.loadTopics().catch(() => {});
            }, delay);
        },

        // Select a topic to filter posts
        selectTopic(topicId) {
            if (this.selectedTopicId === topicId) {
                this.selectedTopicId = null;
            } else {
                this.selectedTopicId = topicId;
                this.tagFilter = null; // Mutually exclusive with tag filter
            }
            this.clearCuration();
            this.loadPosts(true);
        },

        // Clear topic filter
        clearTopicFilter() {
            this.selectedTopicId = null;
            this.loadPosts(true);
        },

        // Get current topic name for display
        getSelectedTopicName() {
            const topic = this.topics.find(t => t.id === this.selectedTopicId);
            return topic ? topic.name : '';
        },

        // Check if a tag belongs to the currently selected topic
        isTopicTag(tag) {
            if (!this.selectedTopicId) return false;
            const topic = this.topics.find(t => t.id === this.selectedTopicId);
            return topic ? topic.tags.includes(tag) : false;
        },

        // Check if a tag is in the user's profile (matched)
        isTagMatched(tag, matchedTags) {
            return (matchedTags || []).some(t => t.toLowerCase() === tag.toLowerCase());
        },

        get blockedUnreadCount() {
            return this.posts.filter(p => !p.is_read && p.is_blocked).length;
        },

        highlightBlockedTitle(title) {
            if (!title || !this.blockedTerms) return this._escHtml(title || '');
            const terms = this.blockedTerms.split('\n').filter(l => l.trim());
            const lower = title.toLowerCase();
            const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            // Collect all matched spans [start, end]
            const spans = [];
            for (const term of terms) {
                if (term.includes('*')) {
                    // With *: regex match with word boundaries on edges
                    const parts = term.split('*').filter(s => s);
                    if (!parts.length) continue;
                    const wb = '(?<![\\p{L}\\p{N}_])';
                    const we = '(?![\\p{L}\\p{N}_])';
                    let pat = parts.map(p => '(' + esc(p) + ')').join('.*?');
                    if (!term.startsWith('*')) pat = wb + pat;
                    if (!term.endsWith('*')) pat = pat + we;
                    const rx = new RegExp(pat, 'giu');
                    let m;
                    while ((m = rx.exec(lower)) !== null) {
                        // Capture groups are 1..parts.length
                        let offset = m.index;
                        for (let g = 1; g <= parts.length; g++) {
                            const gStart = m[0].indexOf(m[g], offset - m.index);
                            spans.push([m.index + gStart, m.index + gStart + m[g].length]);
                        }
                    }
                } else {
                    // Without *: whole word match (Unicode-aware boundaries)
                    const escaped = esc(term);
                    const lb = /[\p{L}\p{N}_]/u.test(term[0]) ? '(?<![\\p{L}\\p{N}_])' : '(?<![\\p{L}\\p{N}_])';
                    const rb = /[\p{L}\p{N}_]/u.test(term[term.length - 1]) ? '(?![\\p{L}\\p{N}_])' : '';
                    const rx = new RegExp(lb + escaped + rb, 'giu');
                    let m;
                    while ((m = rx.exec(lower)) !== null) {
                        spans.push([m.index, m.index + m[0].length]);
                    }
                }
            }
            if (!spans.length) return this._escHtml(title);
            // Merge overlapping spans
            spans.sort((a, b) => a[0] - b[0]);
            const merged = [spans[0]];
            for (let i = 1; i < spans.length; i++) {
                const last = merged[merged.length - 1];
                if (spans[i][0] <= last[1]) {
                    last[1] = Math.max(last[1], spans[i][1]);
                } else {
                    merged.push(spans[i]);
                }
            }
            let result = '';
            let prev = 0;
            for (const [s, e] of merged) {
                result += this._escHtml(title.substring(prev, s));
                result += '<mark class="bg-transparent text-red-500 dark:text-red-400 font-semibold">'
                    + this._escHtml(title.substring(s, e)) + '</mark>';
                prev = e;
            }
            result += this._escHtml(title.substring(prev));
            return result;
        },

        _escHtml(str) {
            const d = document.createElement('div');
            d.textContent = str;
            return d.innerHTML;
        },

        // UI wrappers (delegate to UIStore — keeps existing method calls unchanged)
        applyTheme() { Alpine.store('ui').applyTheme(); },
        get fontScale() { return Alpine.store('ui').fontScale; },
        get fontScaleMin() { return Alpine.store('ui').fontScale === 0; },
        get fontScaleMax() { return Alpine.store('ui').fontScale === Alpine.store('ui').fontScales.length - 1; },
        increaseFontScale() { Alpine.store('ui').increaseFontScale(); },
        decreaseFontScale() { Alpine.store('ui').decreaseFontScale(); },
        resetFontScale() { Alpine.store('ui').resetFontScale(); },
        showToast(message, type = 'info', autoClose = true) {
            Alpine.store('ui').showToast(message, type, autoClose, this.toastTimeoutSeconds);
        },
        showSuccess(message) { this.showToast(message, 'success'); },
        showError(message) { this.showToast(message, 'error'); },
        showInfo(message) { this.showToast(message, 'info'); },
        hideToast() { Alpine.store('ui').hideToast(); },

        // Translate backend error messages
        translateError(message) {
            const key = `backendErrors.${message.replace(/[^a-zA-Z0-9]/g, '_')}`;
            const translated = this.t(key);
            // If translation exists (not the key itself), return it
            return translated !== key ? translated : message;
        },

        showConfirm(message) { return Alpine.store('ui').showConfirm(message); },
        confirmOk() { Alpine.store('ui').confirmOk(); },
        confirmCancel() { Alpine.store('ui').confirmCancel(); },
        confirmLoading(message) { Alpine.store('ui').confirmLoading(message); },
        confirmDone() { Alpine.store('ui').confirmDone(); },

        async loadConfig() {
            try {
                const response = await fetch(`${API_BASE}/admin/config`);
                if (response.ok) {
                    const config = await response.json();
                    if (config.toast_timeout_seconds !== undefined) {
                        this.toastTimeoutSeconds = config.toast_timeout_seconds;
                    }
                    if (config.idle_refresh_seconds !== undefined) {
                        this.idleRefreshSeconds = config.idle_refresh_seconds;
                    }
                }
            } catch (e) {
                // Use default if config fails to load
                console.warn('Failed to load config, using defaults:', e);
            }
        },

        // Initialize
        async init() {
            // Load available locales and summary languages from server first (no auth)
            const i18n = Alpine.store('i18n');
            await Promise.all([
                i18n.loadAvailableLocales(),
                this.loadSummaryLanguages(),
            ]);

            // Detect locale if not in localStorage
            if (!i18n.locale) {
                i18n.locale = i18n.detectBrowserLocale();
            }

            // Load config and translations in parallel
            await Promise.all([
                this.loadConfig(),
                this.loadLocale(this.locale),
            ]);

            // Apply theme and font scale
            this.applyTheme();
            Alpine.store('ui').applyFontScale();
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
                if (this.theme === 'system') {
                    this.applyTheme();
                }
            });

            // Check session validity via /auth/me (cookie-based)
            try {
                await this.fetchApi('/auth/me');
                Alpine.store('auth').authenticated = true;
                // Valid session
                await this.loadData();
                await this.syncPreferences();
                this.loadIgnoredTags();
                if (this.topTagsExpanded) this.loadPopularTags();
                if (this.topicsExpanded) this.loadTopics();
                // Load AI models and prompt defaults (requires auth)
                this.loadAvailableModels();
                this.loadBackgroundAvailableModels();
                this.loadPromptDefaults();
                this.setupIdleDetection();
                this._startPeriodicRefresh();
            } catch (e) {
                // No valid session — login screen shows
            }

            // Setup keyboard shortcuts
            this.setupKeyboardShortcuts();

            // Setup back button handler for modals
            this.setupBackButtonHandler();

            // Tippy.js tooltips: auto-initialize on [data-tip] elements
            this.setupTippy();
        },

        setupTippy() {
            const tippyDefaults = {
                arrow: true,
                delay: [80, 0],
                duration: [120, 100],
                touch: ['hold', 400],
                appendTo: () => document.body,
            };

            // Initialize tippy on a single element
            const initTip = (el) => {
                if (el._tippy) {
                    el._tippy.setContent(el.dataset.tip || '');
                    return;
                }
                const content = el.dataset.tip;
                if (!content) return;
                tippy(el, { ...tippyDefaults, content });
            };

            // Scan and init all [data-tip] elements
            const scanAll = () => {
                document.querySelectorAll('[data-tip]').forEach(initTip);
            };

            // Initial scan
            scanAll();

            // Watch for dynamic elements (Alpine.js renders, list updates)
            const observer = new MutationObserver((mutations) => {
                let needsScan = false;
                for (const m of mutations) {
                    if (m.type === 'childList' && m.addedNodes.length) needsScan = true;
                    if (m.type === 'attributes' && m.attributeName === 'data-tip') {
                        initTip(m.target);
                    }
                }
                if (needsScan) scanAll();
            });
            observer.observe(document.body, {
                childList: true,
                subtree: true,
                attributes: true,
                attributeFilter: ['data-tip'],
            });
        },

        setupBackButtonHandler() {
            window.addEventListener('popstate', (event) => {
                // Back button pressed - close any open modal
                if (this.currentPost) {
                    this.currentPost = null;
                }
                if (this.showSettings) {
                    this._closeSettingsInternal();
                }
            });
        },

        setupKeyboardShortcuts() {
            // Prevent duplicate registration
            if (this._keyboardShortcutsRegistered) return;
            this._keyboardShortcutsRegistered = true;

            document.addEventListener('keydown', (e) => {
                // Ignore key repeat (holding key down)
                if (e.repeat) return;

                // Ignore if in input (except Escape in search)
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
                    if (e.key === 'Escape' && e.target.id === 'search-input') {
                        e.target.blur();
                        this.clearSearch();
                    }
                    return;
                }

                // If confirm modal is open, let it handle its own keys
                if (this.confirmModal.show) {
                    return;
                }

                // If assistant is open
                if (this.showAssistantModal) {
                    if (e.key === 'Escape') {
                        this.showAssistantModal = false;
                    }
                    return;
                }

                // If settings is open
                if (this.showSettings) {
                    if (e.key === 'Escape') {
                        this.closeSettings();
                    }
                    return;
                }

                // If post is open (modal or split pane)
                if (this.currentPost) {
                    if (e.key === 'Escape') {
                        if (this.isSplitMode) {
                            // In split mode, just clear the reading pane
                            this.currentPost = null;
                        } else {
                            this.closePost();
                        }
                        return;
                    } else if (this.isKey(e, 'm')) {
                        this.toggleRead(this.currentPost);
                        return;
                    } else if (this.isKey(e, 's')) {
                        this.toggleStar(this.currentPost);
                        return;
                    } else if (this.isKey(e, 'l')) {
                        this.toggleLike(this.currentPost);
                        return;
                    } else if (this.isKey(e, 'c')) {
                        this.toggleKeepUnread(this.currentPost);
                        return;
                    } else if (this.isKey(e, 'y')) {
                        this.copySummaryToClipboard();
                        return;
                    } else if (this.isKey(e, 'r') && e.shiftKey) {
                        this.regenerateSummary();
                        return;
                    } else if (this.isKey(e, 'r') && !e.shiftKey) {
                        this.refreshFeeds();
                        return;
                    } else if (this.isKey(e, 'i')) {
                        this.openAssistant();
                        return;
                    }
                    // In fullscreen mode, J/K navigate posts within modal
                    if (!this.isSplitMode) {
                        if (this.isKey(e, 'j')) {
                            this.nextPost();
                        } else if (this.isKey(e, 'k')) {
                            this.prevPost();
                        }
                        return;
                    }
                    // In split mode, J/K fall through to selectNext/selectPrev below
                }

                // Main view shortcuts
                if (this.isKey(e, 'j')) {
                    e.preventDefault();
                    this.lastNavMode = 'posts';
                    this.selectNext();
                } else if (this.isKey(e, 'k')) {
                    e.preventDefault();
                    this.lastNavMode = 'posts';
                    this.selectPrev();
                } else if (e.key === 'Enter') {
                    e.preventDefault();
                    if (this.lastNavMode === 'sidebar' && this.filter === 'category' && this.filterId) {
                        this.toggleCategoryCollapse(this.filterId);
                    } else if (this.selectedIndex >= 0 && this.posts[this.selectedIndex]) {
                        this.openPost(this.posts[this.selectedIndex]);
                    }
                } else if (this.isKey(e, 'm')) {
                    if (this.selectMode && this.selectedPosts.size > 0) {
                        this.markSelectedAsRead();
                    } else if (this.selectedIndex >= 0 && this.posts[this.selectedIndex]) {
                        this.toggleRead(this.posts[this.selectedIndex]);
                    }
                } else if (this.isKey(e, 's')) {
                    if (this.selectedIndex >= 0 && this.posts[this.selectedIndex]) {
                        this.toggleStar(this.posts[this.selectedIndex]);
                    }
                } else if (this.isKey(e, 'c')) {
                    if (this.selectedIndex >= 0 && this.posts[this.selectedIndex]) {
                        this.toggleKeepUnread(this.posts[this.selectedIndex]);
                    }
                } else if (this.isKey(e, 'r')) {
                    this.refreshFeeds();
                } else if (this.isKey(e, 'x')) {
                    this.toggleSelectMode();
                } else if (this.isKey(e, 'a')) {
                    this.markAllRead();
                } else if (this.isKey(e, 'n')) {
                    this.markAllRead(true);
                } else if (e.key === ' ' && this.selectMode) {
                    e.preventDefault();
                    if (this.selectedIndex >= 0 && this.posts[this.selectedIndex]) {
                        this.togglePostSelection(this.posts[this.selectedIndex].id);
                    }
                } else if (e.key === '[') {
                    this.lastNavMode = 'sidebar';
                    this.prevFeed();
                } else if (e.key === ']') {
                    this.lastNavMode = 'sidebar';
                    this.nextFeed();
                } else if (e.key === '/') {
                    e.preventDefault();
                    const si = document.getElementById('search-input');
                    if (si) si.focus();
                }
            });
        },

        // Sidebar navigation - builds ordered list matching sidebar visual order
        getNavigableItems() {
            const items = [];

            // Unread
            items.push({ type: 'unread' });

            // Suggested (only if there are suggestions)
            if (this.suggestedCount > 0) {
                items.push({ type: 'suggested' });
            }

            // Categories and their feeds
            for (const category of this.categories) {
                const categoryUnread = this.getCategoryUnread(category.id);
                if (categoryUnread > 0) {
                    items.push({ type: 'category', id: category.id });
                }

                // Only include feeds if category is not collapsed
                if (!this.isCategoryCollapsed(category.id)) {
                    const categoryFeeds = this.feeds.filter(
                        f => f.category_id === category.id && f.unread_count > 0
                    );
                    for (const feed of categoryFeeds) {
                        items.push({ type: 'feed', id: feed.id });
                    }
                }
            }

            // Uncategorized feeds
            const uncategorized = this.feeds.filter(
                f => !f.category_id && f.unread_count > 0
            );
            for (const feed of uncategorized) {
                items.push({ type: 'feed', id: feed.id });
            }

            return items;
        },

        getCurrentItemIndex(items) {
            return items.findIndex(item => {
                if (item.type === 'unread' && this.filter === 'unread') return true;
                if (item.type === 'suggested' && this.filter === 'suggested') return true;
                if (item.type === 'category' && this.filter === 'category' && this.filterId === item.id) return true;
                if (item.type === 'feed' && this.filter === 'feed' && this.filterId === item.id) return true;
                return false;
            });
        },

        navigateToItem(item) {
            if (item.type === 'unread') {
                this.setFilter('unread');
            } else if (item.type === 'suggested') {
                this.setFilter('suggested');
            } else if (item.type === 'category') {
                this.setFilter('category', item.id);
            } else if (item.type === 'feed') {
                this.setFilter('feed', item.id);
            }
        },

        prevFeed() {
            const items = this.getNavigableItems();
            if (items.length === 0) return;

            const currentIndex = this.getCurrentItemIndex(items);

            if (currentIndex !== -1) {
                // Found current position - navigate to previous
                const prevIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
                this.lastFeedNavIndex = prevIndex;
                this.navigateToItem(items[prevIndex]);
            } else {
                // Current filter not in list (e.g., after mark all read)
                // Item at lastFeedNavIndex was removed, previous item is at lastFeedNavIndex - 1
                const targetIndex = Math.max(this.lastFeedNavIndex - 1, 0);
                this.lastFeedNavIndex = targetIndex;
                this.navigateToItem(items[targetIndex]);
            }
        },

        nextFeed() {
            const items = this.getNavigableItems();
            if (items.length === 0) return;

            const currentIndex = this.getCurrentItemIndex(items);

            if (currentIndex !== -1) {
                // Found current position - navigate to next
                const nextIndex = (currentIndex + 1) % items.length;
                this.lastFeedNavIndex = nextIndex;
                this.navigateToItem(items[nextIndex]);
            } else {
                // Current filter not in list (e.g., after mark all read)
                // Item at lastFeedNavIndex was removed, next item shifted down to lastFeedNavIndex
                // If lastFeedNavIndex is past the end, wrap around to beginning
                const targetIndex = this.lastFeedNavIndex < items.length
                    ? this.lastFeedNavIndex
                    : 0;
                this.lastFeedNavIndex = targetIndex;
                this.navigateToItem(items[targetIndex]);
            }
        },

        // Auth methods
        async login() {
            this.logging = true;
            this.loginError = null;

            try {
                const response = await fetch(`${API_BASE}/auth/login`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ password: this.password }),
                });

                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.detail || this.t('errors.loginFailed'));
                }

                this.password = '';
                Alpine.store('auth').authenticated = true;
                await this.loadData();
                await this.syncPreferences();
                this.loadIgnoredTags();
                if (this.topTagsExpanded) this.loadPopularTags();
                if (this.topicsExpanded) this.loadTopics();
                // Load AI models and prompt defaults (requires auth)
                this.loadAvailableModels();
                this.loadPromptDefaults();
                this.setupIdleDetection();
            } catch (error) {
                this.loginError = error.message;
            } finally {
                this.logging = false;
            }
        },

        async logout() {
            try {
                await this.fetchApi('/auth/logout', { method: 'POST' });
            } catch (e) {
                // Ignore logout errors — network may be unavailable
                console.debug('Logout request failed:', e);
            }
            Alpine.store('auth').authenticated = false;
            this.resetFontScale();
            this.feeds = [];
            this.categories = [];
            this.posts = [];
            this.currentPost = null;
        },

        // API helper (delegates to AuthStore)
        async fetchApi(endpoint, options = {}) {
            try {
                return await Alpine.store('auth').fetchApi(endpoint, options);
            } catch (error) {
                // Handle 401 — session expired
                if (Alpine.store('auth').authenticated && error.message === 'Session expired') {
                    Alpine.store('auth').authenticated = false;
                    this.feeds = [];
                    this.categories = [];
                    this.posts = [];
                    this.currentPost = null;
                    throw new Error(this.t('errors.sessionExpired'));
                }
                throw error;
            }
        },

        // Data loading
        async loadData() {
            await Promise.all([
                this.loadFeeds(),
                this.loadCategories(),
            ]);
            await this.loadPosts(true);
            this.checkHealth();
        },

        async loadFeeds() {
            try {
                this.feeds = await this.fetchApi('/feeds');
            } catch (error) {
                console.error('Failed to load feeds:', error);
            }
        },

        async loadCategories() {
            try {
                this.categories = await this.fetchApi('/categories');
            } catch (error) {
                console.error('Failed to load categories:', error);
            }
        },

        async loadPosts(reset = false) {
            if (this.loading) {
                if (reset) this._pendingReload = true;
                return;
            }

            if (reset) {
                this.posts = [];
                this.offset = 0;
                this.hasMore = true;
                this.selectedIndex = -1;
            }

            this.loading = true;

            try {
                const params = new URLSearchParams({
                    offset: this.offset,
                    limit: this.pageSize,
                });

                // Apply feed/category filter
                if (this.filter === 'feed') {
                    params.set('feed_id', this.filterId);
                } else if (this.filter === 'category') {
                    params.set('category_id', this.filterId);
                }

                // Apply topic or tag filter (mutually exclusive)
                if (this.selectedTopicId) {
                    params.set('topic_id', this.selectedTopicId);
                } else if (this.tagFilter) {
                    params.set('tag', this.tagFilter);
                }

                // Apply post filter (unread/all/starred/suggested within current context)
                // When sidebar filter is 'starred', always show starred posts
                if (this.filter === 'starred' || this.postFilter === 'starred') {
                    params.set('starred_only', 'true');
                } else if (this.filter === 'suggested') {
                    params.set('suggested_only', 'true');
                    // Also respect unread filter in suggested view
                    if (this.postFilter === 'unread') {
                        params.set('unread_only', 'true');
                    }
                } else if (this.postFilter === 'unread') {
                    params.set('unread_only', 'true');
                }
                // postFilter === 'all' doesn't add any filter

                if (this.searchQuery.trim()) {
                    params.set('search', this.searchQuery.trim());
                }

                const data = await this.fetchApi(`/posts?${params}`);

                if (reset) {
                    this.posts = data.posts;
                } else {
                    this.posts = [...this.posts, ...data.posts];
                }

                this.hasMore = data.has_more || false;
                this.offset += data.posts.length;

                // Update tag filter count when tag filter is active
                if (this.tagFilter && reset) {
                    this.tagFilterCount = data.total || 0;
                }

                // Update feed unread counts if provided by the API
                if (data.feed_unread_counts) {
                    for (const [feedId, count] of Object.entries(data.feed_unread_counts)) {
                        const feed = this.feeds.find(f => f.id === parseInt(feedId));
                        if (feed) {
                            feed.unread_count = count;
                        }
                    }
                }

                // Update starred count for current context
                if (data.starred_count !== undefined) {
                    this.starredCount = data.starred_count;
                }

                // Update suggested count
                if (data.suggested_count !== undefined) {
                    this.suggestedCount = data.suggested_count;
                }

                // Refresh top tags when context changes
                if (reset) this.loadPopularTags();

                // Select pending post after feed navigation
                if (this._pendingPostId) {
                    let idx = this.posts.findIndex(p => p.id === this._pendingPostId);
                    if (idx === -1 && this._pendingPost) {
                        // Post not in list (already read with unread filter) — inject at chronological position
                        const postDate = this._pendingPost.published_at || this._pendingPost.fetched_at || '';
                        idx = this.posts.findIndex(p => (p.published_at || p.fetched_at || '') < postDate);
                        if (idx === -1) idx = this.posts.length;
                        this.posts.splice(idx, 0, this._pendingPost);
                        this.offset += 1;
                    }
                    if (idx !== -1) {
                        this.selectedIndex = idx;
                        this.$nextTick(() => this.scrollToSelected(true));
                        if (this._pendingOpenPost) {
                            this.$nextTick(() => this.openPost(this.posts[idx] || this._pendingOpenPost));
                        }
                    }
                    this._pendingPostId = null;
                    this._pendingPost = null;
                    this._pendingOpenPost = null;
                }
            } catch (error) {
                console.error('Failed to load posts:', error);
            } finally {
                this.loading = false;
                if (this._pendingReload) {
                    this._pendingReload = false;
                    await this.loadPosts(true);
                }
            }
        },

        async checkHealth() {
            try {
                const data = await this.fetchApi('/admin/status');
                this.healthWarning = data.health_warning;
            } catch (e) {
                // Ignore health check errors — server may be temporarily unavailable
                console.debug('Health check failed:', e);
            }
        },

        // Filters
        navigateToFeed(feedId, postId, postData = null) {
            // Already on this feed — no reload needed, just find/scroll/open the post
            if (this.filter === 'feed' && this.filterId === feedId) {
                let idx = this.posts.findIndex(p => p.id === postId);
                if (idx === -1 && postData) {
                    const postDate = postData.published_at || postData.fetched_at || '';
                    idx = this.posts.findIndex(p => (p.published_at || p.fetched_at || '') < postDate);
                    if (idx === -1) idx = this.posts.length;
                    this.posts.splice(idx, 0, postData);
                    this.offset += 1;
                }
                if (idx !== -1) {
                    this.selectedIndex = idx;
                    this.$nextTick(() => {
                        this.scrollToSelected(true);
                        if (this._pendingOpenPost) {
                            this.openPost(this.posts[idx] || postData);
                            this._pendingOpenPost = null;
                        }
                    });
                }
                return;
            }
            // Expand the feed's category if it's collapsed
            const feed = this.feeds.find(f => f.id === feedId);
            if (feed && this.collapsedCategories.has(feed.category_id)) {
                this.collapsedCategories.delete(feed.category_id);
                localStorage.setItem('rss_collapsed_categories', JSON.stringify([...this.collapsedCategories]));
                // Force Alpine reactivity
                this.collapsedCategories = new Set(this.collapsedCategories);
            }
            this._pendingPostId = postId;
            // Use post from current list, or fall back to caller-supplied data (e.g. from relatedPosts)
            this._pendingPost = this.posts.find(p => p.id === postId) || postData || null;
            this.setFilter('feed', feedId);
        },

        setFilter(type, id = null) {
            this.filter = type;
            this.filterId = id;
            this.tagFilter = null; // Clear tag filter on navigation
            this.selectedTopicId = null; // Clear topic filter on navigation
            this.clearCuration();
            this.sidebarOpen = false; // Close sidebar on mobile

            // Update lastFeedNavIndex for navigable filters (so [/] works after clicking)
            const items = this.getNavigableItems();
            const idx = this.getCurrentItemIndex(items);
            if (idx !== -1) {
                this.lastFeedNavIndex = idx;
            }

            this.loadPosts(true);
        },

        getFilterTitle() {
            let title = '';
            if (this.filter === 'unread') {
                title = this.t('sidebar.unread');
            } else if (this.filter === 'starred') {
                title = this.t('sidebar.starred');
            } else if (this.filter === 'suggested') {
                title = this.t('sidebar.suggested');
            } else if (this.filter === 'feed') {
                const feed = this.feeds.find(f => f.id === this.filterId);
                title = feed ? feed.title : 'Feed';
            } else if (this.filter === 'category') {
                const cat = this.categories.find(c => c.id === this.filterId);
                title = cat ? cat.name : this.t('settings.tabs.categories');
            }
            return title;
        },

        getCategoryUnread(categoryId) {
            return this.feeds
                .filter(f => f.category_id === categoryId)
                .reduce((sum, f) => sum + (f.unread_count || 0), 0);
        },

        toggleCategoryCollapse(categoryId) {
            if (this.collapsedCategories.has(categoryId)) {
                this.collapsedCategories.delete(categoryId);
            } else {
                this.collapsedCategories.add(categoryId);
            }
            localStorage.setItem('rss_collapsed_categories', JSON.stringify([...this.collapsedCategories]));
        },

        isCategoryCollapsed(categoryId) {
            return this.collapsedCategories.has(categoryId);
        },

        getFeedTitle(feedId) {
            const feed = this.feeds.find(f => f.id === feedId);
            return feed ? feed.title : this.t('time.unknown');
        },

        getFeedSiteUrl(feedId) {
            const feed = this.feeds.find(f => f.id === feedId);
            return feed ? feed.site_url : null;
        },

        async toggleRead(post) {
            if (post.keep_unread && !post.is_read) {
                this.showToast(this.t('keepUnread.protected'), 'error');
                return;
            }
            const newState = !post.is_read;
            await this.markPostRead(post, newState);
        },

        async markPostRead(post, isRead) {
            try {
                await this.fetchApi(`/posts/${post.id}/read`, {
                    method: 'PATCH',
                    body: JSON.stringify({ is_read: isRead }),
                });

                this.updatePost(post.id, { is_read: isRead });
                this._adjustUnreadCounters(post, isRead);
            } catch (error) {
                console.error('Failed to mark post read:', error);
            }
        },

        async toggleStar(post) {
            // Warn if starring into a feed that already has many starred posts
            if (!post.is_starred) {
                const feed = this.feeds.find(f => f.id === post.feed_id);
                if (feed && (feed.starred_count || 0) >= CURATION_WARN_THRESHOLD) {
                    if (!await this.showConfirm(
                        this.t('starring.tooManyStarred')
                            .replace('{count}', feed.starred_count)
                            .replace('{feed}', feed.title)
                    )) return;
                    this.confirmDone();
                }
            }
            try {
                const data = await this.fetchApi(`/posts/${post.id}/star`, {
                    method: 'PATCH',
                });

                this.updatePost(post.id, {
                    is_starred: data.is_starred,
                    starred_at: data.starred_at,
                    is_liked: data.is_liked,  // Auto-like when starring
                });

                // Update global/contextual starred count
                if (data.is_starred === true) {
                    this.starredCount++;
                } else {
                    this.starredCount = Math.max(0, this.starredCount - 1);
                }

                // Update feed's starred count (for settings modal)
                const feed = this.feeds.find(f => f.id === post.feed_id);
                if (feed) {
                    if (data.is_starred === true) {
                        feed.starred_count = (feed.starred_count || 0) + 1;
                    } else {
                        feed.starred_count = Math.max(0, (feed.starred_count || 0) - 1);
                    }
                }
            } catch (error) {
                console.error('Failed to toggle star:', error);
            }
        },

        async toggleLike(post) {
            try {
                const data = await this.fetchApi(`/posts/${post.id}/like`, {
                    method: 'PATCH',
                });

                this.updatePost(post.id, {
                    is_liked: data.is_liked,
                    liked_at: data.liked_at,
                });
            } catch (error) {
                console.error('Failed to toggle like:', error);
            }
        },

        async toggleKeepUnread(post) {
            const wasRead = post.is_read;
            try {
                const data = await this.fetchApi(`/posts/${post.id}/keep-unread`, {
                    method: 'PATCH',
                });

                this.updatePost(post.id, {
                    keep_unread: data.keep_unread,
                    is_read: data.is_read,
                    read_at: data.read_at,
                });

                // If post was forced back to unread, update counters
                if (wasRead && !data.is_read) {
                    this._adjustUnreadCounters(post, false);
                }
            } catch (error) {
                console.error('Failed to toggle keep unread:', error);
            }
        },

        // Shared helper for adjusting unread counters after read-state change
        _adjustUnreadCounters(post, isRead) {
            const feed = this.feeds.find(f => f.id === post.feed_id);
            if (feed) {
                feed.unread_count = Math.max(0, (feed.unread_count || 0) + (isRead ? -1 : 1));
            }
            if (post.is_suggested) {
                if (isRead) {
                    this.suggestedCount = Math.max(0, this.suggestedCount - 1);
                } else {
                    this.suggestedCount++;
                }
            }
            // Adjust topic unread counts locally (a post counts once per topic
            // whose tags it shares) instead of refetching the whole list.
            if (this.topicsExpanded && Array.isArray(post.tags) && post.tags.length) {
                const postTags = new Set(post.tags);
                const delta = isRead ? -1 : 1;
                for (const topic of this.topics) {
                    if ((topic.tags || []).some(t => postTags.has(t))) {
                        topic.unread_count = Math.max(0, (topic.unread_count || 0) + delta);
                    }
                }
            }
        },

        // Periodic silent refresh of sidebar counts (every 60s)
        _periodicRefreshInterval: null,
        _startPeriodicRefresh() {
            this._stopPeriodicRefresh();
            this._periodicRefreshInterval = setInterval(() => {
                this.loadFeeds().catch(() => {});
                this.scheduleTopicsRefresh();
            }, 60000);
        },
        _stopPeriodicRefresh() {
            if (this._periodicRefreshInterval) {
                clearInterval(this._periodicRefreshInterval);
                this._periodicRefreshInterval = null;
            }
        },

        async markAllRead(blockedOnly = false) {
            // Get unread posts currently visible in the interface
            // This ensures we only mark posts the user has seen, not new ones
            // that may have arrived via background refresh
            const visibleUnreadIds = this.posts
                .filter(p => !p.is_read && !p.keep_unread && (!blockedOnly || p.is_blocked))
                .map(p => p.id);

            if (visibleUnreadIds.length === 0) return;

            // Determine context name for confirmation
            let contextName = '';
            if (this.filter === 'feed') {
                const feed = this.feeds.find(f => f.id === this.filterId);
                contextName = feed?.title || 'feed';
            } else if (this.filter === 'category') {
                const category = this.categories.find(c => c.id === this.filterId);
                contextName = category?.name || this.t('settings.tabs.categories');
            } else if (this.filter === 'suggested') {
                contextName = this.t('sidebar.suggested');
            } else if (this.filter === 'starred') {
                contextName = this.t('sidebar.starred');
            } else {
                contextName = this.t('confirm.allPosts');
            }
            // Append active filter qualifiers
            if (this.searchQuery.trim()) {
                contextName += ` — ${this.t('confirm.searchResults')}: '${this.searchQuery.trim()}'`;
            }
            if (this.tagFilter) {
                contextName += ` — tag: #${this.tagFilter}`;
            }
            if (this.selectedTopicId) {
                const topic = this.topics.find(t => t.id === this.selectedTopicId);
                if (topic) contextName += ` — ${this.t('confirm.topic')}: ${topic.name}`;
            }

            // Ask for confirmation
            const msgKey = blockedOnly ? 'confirm.markBlockedRead' : 'confirm.markAllRead';
            const msg = this.t(msgKey)
                .replace('{count}', visibleUnreadIds.length)
                .replace('{context}', contextName);

            if (!await this.showConfirm(msg)) return;

            // Show loading state in modal
            this.confirmLoading(this.t('confirm.markingAsRead'));

            try {
                await this.fetchApi('/posts/mark-read', {
                    method: 'POST',
                    body: JSON.stringify({ post_ids: visibleUnreadIds }),
                });

                // Reload data
                await this.loadFeeds();
                this.scheduleTopicsRefresh(0);
                await this.loadPosts(true);
            } catch (error) {
                console.error('Failed to mark all read:', error);
            } finally {
                this.confirmDone();
            }
        },

        // Refresh
        async refreshFeeds() {
            if (this.refreshing) return;
            this.refreshing = true;

            try {
                const feedsToRefresh = [...this.feeds]; // All feeds
                const total = feedsToRefresh.length;
                let totalNew = 0;
                let current = 0;

                for (const feed of feedsToRefresh) {
                    current++;
                    this.showInfo(this.t('refresh.updating').replace('{current}', current).replace('{total}', total).replace('{title}', feed.title.substring(0, 30)));

                    try {
                        const result = await this.fetchApi(`/feeds/${feed.id}/refresh`, { method: 'POST' });
                        if (result && result.new_posts > 0) {
                            totalNew += result.new_posts;
                        }
                    } catch (e) {
                        console.error(`Failed to refresh feed ${feed.id}:`, e);
                    }
                }

                // Only reload UI if there are new posts
                if (totalNew > 0) {
                    await this.loadFeeds();
                    this.scheduleTopicsRefresh(0);
                    await this.loadPosts(true);
                    this.showSuccess(this.t('refresh.newPosts').replace('{count}', totalNew));

                    // Process suggestions for new posts (fire and forget)
                    this.fetchApi('/suggestions/admin/process-suggestions', { method: 'POST' })
                        .then(result => {
                            if (result && result.success && result.message) {
                                // Update suggested count if new suggestions were found
                                const match = result.message.match(/(\d+) new suggestions/);
                                if (match && parseInt(match[1]) > 0) {
                                    this.suggestedCount += parseInt(match[1]);
                                }
                            }
                        })
                        .catch(() => {}); // Ignore errors
                } else {
                    this.showInfo(this.t('refresh.noNewPosts'));
                }
            } finally {
                this.refreshing = false;
            }
        },

        // Navigation
        selectNext() {
            if (this.selectedIndex < this.posts.length - 1) {
                this.selectedIndex++;
                this.scrollToSelected();
                // Auto-open in split mode
                if (this.isSplitMode && this.posts[this.selectedIndex]) {
                    this.openPost(this.posts[this.selectedIndex]);
                }
            }
        },

        selectPrev() {
            if (this.selectedIndex > 0) {
                this.selectedIndex--;
                this.scrollToSelected();
                // Auto-open in split mode
                if (this.isSplitMode && this.posts[this.selectedIndex]) {
                    this.openPost(this.posts[this.selectedIndex]);
                }
            }
        },

        scrollToSelected(toTop = false) {
            // Use setTimeout to ensure DOM is fully updated (more reliable on mobile)
            setTimeout(() => {
                const el = document.querySelector(`[data-index="${this.selectedIndex}"]`);
                if (!el) return;

                try {
                    el.scrollIntoView({ block: toTop ? 'start' : 'nearest', behavior: 'smooth' });
                } catch (e) {
                    el.scrollIntoView(false);
                }
            }, 50);
        },

        // Infinite scroll
        handleScroll(event) {
            const el = event.target;
            const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200;

            if (nearBottom && this.hasMore && !this.loading) {
                this.loadPosts();
            }
        },

        // Selection
        toggleSelectMode() {
            this.selectMode = !this.selectMode;
            if (!this.selectMode) {
                this.selectedPosts.clear();
            }
        },

        togglePostSelection(postId) {
            if (this.selectedPosts.has(postId)) {
                this.selectedPosts.delete(postId);
            } else {
                this.selectedPosts.add(postId);
            }
            // Force reactivity
            this.selectedPosts = new Set(this.selectedPosts);
        },

        isPostSelected(postId) {
            return this.selectedPosts.has(postId);
        },

        selectAllVisible() {
            this.posts.forEach(p => this.selectedPosts.add(p.id));
            this.selectedPosts = new Set(this.selectedPosts);
        },

        deselectAll() {
            this.selectedPosts.clear();
            this.selectedPosts = new Set(this.selectedPosts);
        },

        async markSelectedAsRead() {
            if (this.selectedPosts.size === 0) return;

            const postIds = Array.from(this.selectedPosts).filter(id => {
                const p = this.posts.find(post => post.id === id);
                return p && !p.keep_unread;
            });
            if (postIds.length === 0) return;

            try {
                await this.fetchApi('/posts/mark-read', {
                    method: 'POST',
                    body: JSON.stringify({ post_ids: postIds }),
                });

                // Update local state (only non-protected posts)
                this.posts.forEach(p => {
                    if (postIds.includes(p.id)) {
                        p.is_read = true;
                    }
                });

                // Update feed and topic unread counts
                await this.loadFeeds();
                this.scheduleTopicsRefresh(0);

                // Clear selection
                this.selectedPosts.clear();
                this.selectedPosts = new Set(this.selectedPosts);
                this.selectMode = false;

                // Reload if showing unread only
                if (this.postFilter === 'unread') {
                    await this.loadPosts(true);
                }
            } catch (error) {
                console.error('Failed to mark posts as read:', error);
                this.showError(this.t('errors.markPostsRead'));
            }
        },

        // Regenerate suggestions
        async regenerateSuggestions() {
            if (this.regeneratingSuggestions) return;
            this.regeneratingSuggestions = true;

            try {
                // Regenerate profile first, then process suggestions
                const profileResult = await this.fetchApi('/suggestions/admin/regenerate-profile', { method: 'POST' });
                const tagsMatch = profileResult?.message?.match(/(\d+) tags/);
                const tagsCount = tagsMatch ? parseInt(tagsMatch[1]) : 0;

                const result = await this.fetchApi('/suggestions/admin/process-suggestions', { method: 'POST' });

                if (result && result.success) {
                    const match = result.message.match(/(\d+) new suggestions/);
                    const count = match ? parseInt(match[1]) : 0;
                    this.showSuccess(
                        this.t('sidebar.suggestionsFound')
                            .replace('{count}', count)
                            .replace('{tags}', tagsCount)
                    );
                    // Reload posts and counts
                    await this.loadPosts(true);
                } else {
                    this.showError(result?.message || this.t('errors.requestFailed'));
                }
            } catch (error) {
                console.error('Failed to regenerate suggestions:', error);
                this.showError(this.t('errors.requestFailed'));
            } finally {
                this.regeneratingSuggestions = false;
            }
        },

        // Formatting
        formatDate(dateStr) {
            if (!dateStr) return '';

            // Force UTC timezone if string is ISO without explicit timezone offset
            let formattedStr = dateStr;
            if (typeof dateStr === 'string' && !dateStr.endsWith('Z') && !dateStr.includes('+')) {
                // If it contains 'T' (ISO format) but doesn't specify timezone, treat as UTC
                const hasTimezone = (dateStr.substring(dateStr.indexOf('T')).match(/[\-+]\d{2}/) !== null);
                if (dateStr.includes('T') && !hasTimezone) {
                    formattedStr = dateStr + 'Z';
                }
            }

            const MINUTE = 60000;
            const HOUR = 3600000;
            const DAY = 86400000;
            const WEEK = 604800000;

            const date = new Date(formattedStr);
            const now = new Date();
            const diff = now - date;

            if (diff < HOUR) {
                const mins = Math.floor(diff / MINUTE);
                return mins <= 1 ? this.t('time.now') : `${mins}min`;
            }

            if (diff < DAY) {
                const hours = Math.floor(diff / HOUR);
                return `${hours}h`;
            }

            if (diff < WEEK) {
                const days = Math.floor(diff / DAY);
                return `${days}d`;
            }

            return date.toLocaleDateString('pt-BR', {
                day: 'numeric',
                month: 'short',
            });
        },

        // Check if we should show a date separator before a post
        shouldShowDateSeparator(index) {
            if (index === 0) return true;

            const currentPost = this.posts[index];
            const prevPost = this.posts[index - 1];

            const currentGroup = this.formatDate(currentPost.published_at || currentPost.fetched_at);
            const prevGroup = this.formatDate(prevPost.published_at || prevPost.fetched_at);

            return currentGroup !== prevGroup;
        },


        // Idle detection - auto refresh unread counts after inactivity
        setupIdleDetection() {
            // Skip if idle refresh is disabled (0 seconds)
            if (this.idleRefreshSeconds <= 0) return;

            const events = ['mousedown', 'mousemove', 'keydown', 'scroll', 'touchstart', 'click'];
            events.forEach(event => {
                document.addEventListener(event, () => this.resetIdleTimer(), { passive: true });
            });

            // Start initial timer
            this.resetIdleTimer();
        },

        resetIdleTimer() {
            // Clear existing timer
            if (this.idleTimeoutId) {
                clearTimeout(this.idleTimeoutId);
            }

            // Set new timer
            this.idleTimeoutId = setTimeout(() => this.onIdle(), this.idleRefreshSeconds * 1000);
        },

        async onIdle() {
            // Don't refresh if modal is open or already refreshing
            if (this.currentPost || this.showSettings || this.refreshing) {
                // Restart timer to check again later
                this.resetIdleTimer();
                return;
            }

            // Refresh feed and topic unread counts silently
            try {
                await this.loadFeeds();
                this.scheduleTopicsRefresh();
            } catch (e) {
                // Ignore errors on idle refresh — will retry on next cycle
                console.debug('Idle refresh failed:', e);
            }

            // Restart timer for next idle check
            this.resetIdleTimer();
        },

        // ── Search ──

        onSearchInput() {
            clearTimeout(this._searchTimeout);
            this._searchTimeout = setTimeout(() => {
                this.loadPosts(true);
            }, 300);
        },

        clearSearch() {
            this.searchQuery = '';
            this.loadPosts(true);
        },

        // ── Drag-and-drop: move feed between categories ──

        onFeedDragStart(event, feedId) {
            this.dragFeedId = feedId;
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', String(feedId));
            event.target.style.opacity = '0.5';
        },

        onFeedDragEnd(event) {
            event.target.style.opacity = '';
            this.dragFeedId = null;
            this.dragOverCategoryId = null;
        },

        onCategoryDragOver(event, categoryId) {
            if (this.dragFeedId === null) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = 'move';
            this.dragOverCategoryId = categoryId;
        },

        onCategoryDragLeave(event, categoryId) {
            if (!event.currentTarget.contains(event.relatedTarget)) {
                if (this.dragOverCategoryId === categoryId) {
                    this.dragOverCategoryId = null;
                }
            }
        },

        async onCategoryDrop(event, categoryId) {
            event.preventDefault();
            const feedId = this.dragFeedId;
            this.dragOverCategoryId = null;
            this.dragFeedId = null;

            if (!feedId) return;

            const feed = this.feeds.find(f => f.id === feedId);
            if (!feed || feed.category_id === categoryId) return;

            const oldCategoryId = feed.category_id;
            feed.category_id = categoryId;

            try {
                await this.fetchApi(`/feeds/${feedId}`, {
                    method: 'PUT',
                    body: JSON.stringify({ category_id: categoryId }),
                });
                this.showSuccess(this.t('feeds.moved'));
            } catch (error) {
                feed.category_id = oldCategoryId;
                this.showError(this.t('errors.moveFeed'));
            }
        },
    };
}
