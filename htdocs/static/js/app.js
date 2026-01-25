/**
 * Risos - Alpine.js Application
 */

const APP_VERSION = '20260125b';
const API_BASE = '/api';

function app() {
    return {
        // App info
        appVersion: APP_VERSION,

        // Authentication
        token: null,
        password: '',
        logging: false,
        loginError: null,

        // Data
        feeds: [],
        categories: [],
        posts: [],
        currentPost: null,

        // UI State
        filter: 'unread',
        filterId: null,
        loading: false,
        loadingContent: false,
        refreshing: false,
        refreshingFeed: false,
        regeneratingSummary: false,
        selectedIndex: -1,
        hasMore: true,
        offset: 0,
        pageSize: 50,
        postFilter: 'unread', // 'unread', 'all', or 'starred'
        selectedPosts: new Set(),
        selectMode: false,
        collapsedCategories: new Set(JSON.parse(localStorage.getItem('rss_collapsed_categories') || '[]')),
        sidebarOpen: false,
        lastNavMode: 'posts', // 'posts' (J/K) or 'sidebar' ([/])
        lastFeedNavIndex: 0, // Last position in feed navigation (for [/])

        // Settings
        showSettings: false,
        settingsTab: 'categories',
        settingsAccordion: { appearance: true, ai: false, data: false, interface: false }, // Accordion open state
        newCategoryName: '',
        newFeed: { url: '', category_id: '' },
        editingCategory: null,
        editingFeed: null,
        savingCategory: false,
        savingFeed: false,
        importingOpml: false,
        opmlResult: null,

        // Health
        healthWarning: null,

        // Idle detection
        idleTimeoutId: null,
        idleRefreshSeconds: 180, // Default 3 minutes, loaded from config

        // Suggestions
        suggestionMinTags: 3, // Default 3 tags overlap required

        // Reading mode
        readingMode: 'fullscreen', // 'fullscreen' or 'split', loaded from server
        splitRatio: 40, // percentage for posts panel (20-80), loaded from server
        resizing: false, // true while dragging the resize handle

        // Toast
        toast: {
            show: false,
            message: '',
            type: 'info', // 'success', 'error', 'info'
            timeoutId: null,
        },
        toastTimeoutSeconds: 2, // Default, will be loaded from config

        // Confirm modal
        confirmModal: {
            show: false,
            message: '',
            resolve: null,
            loading: false,
        },

        // i18n
        locale: localStorage.getItem('rss_locale') || null, // Will be detected in init()
        translations: {},
        availableLocales: [], // Loaded from server

        // Load available locales from server
        async loadAvailableLocales() {
            try {
                const response = await fetch(`${API_BASE}/admin/locales`);
                if (response.ok) {
                    this.availableLocales = await response.json();
                }
            } catch (e) {
                console.warn('Failed to load available locales:', e);
                // Fallback to hardcoded list
                this.availableLocales = [
                    { code: 'en-US', name: 'English (US)' },
                    { code: 'pt-BR', name: 'Português (Brasil)' }
                ];
            }
        },

        // Detect browser language and return matching locale or fallback
        detectBrowserLocale() {
            const browserLang = navigator.language || navigator.userLanguage || 'en-US';
            // Check if we have an exact match
            const exact = this.availableLocales.find(l => l.code === browserLang);
            if (exact) return exact.code;
            // Check for partial match (e.g., 'pt' matches 'pt-BR')
            const lang = browserLang.split('-')[0];
            const partial = this.availableLocales.find(l => l.code.startsWith(lang));
            if (partial) return partial.code;
            // Fallback to first available or English
            return this.availableLocales[0]?.code || 'en-US';
        },

        // Theme
        theme: localStorage.getItem('rss_theme') || 'system',
        availableThemes: [
            { value: 'system', labelKey: 'settings.themeSystem' },
            { value: 'light', labelKey: 'settings.themeLight' },
            { value: 'dark', labelKey: 'settings.themeDark' }
        ],

        // AI Settings
        summaryLanguage: null, // Loaded from server preferences
        cerebrasModel: null,   // Loaded from server preferences
        availableSummaryLanguages: [], // Loaded from server
        availableModels: [], // Loaded from server (requires auth)

        // Data Settings
        feedUpdateInterval: 30,  // Loaded from server preferences
        maxPostsPerFeed: 500,
        maxPostAgeDays: 365,
        maxUnreadDays: 90,

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

        get opmlResultText() {
            if (!this.opmlResult) return '';
            const { imported, skipped, errors } = this.opmlResult;
            let text = `${imported} ${this.t('opml.imported')}`;
            if (skipped > 0) text += `, ${skipped} ${this.t('opml.duplicates')}`;
            if (errors?.length > 0) text += `, ${errors.length} ${this.t('opml.errors')}`;
            return text;
        },

        // Post lookup helpers
        getPostById(id) {
            return this.posts.find(p => p.id === id);
        },

        getPostIndex(id) {
            return this.posts.findIndex(p => p.id === id);
        },

        getCurrentPostIndex() {
            return this.currentPost ? this.getPostIndex(this.currentPost.id) : -1;
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

        // Translation function
        t(key, fallback = null) {
            const keys = key.split('.');
            let value = this.translations;
            for (const k of keys) {
                if (value && typeof value === 'object' && k in value) {
                    value = value[k];
                } else {
                    return fallback || key;
                }
            }
            return value || fallback || key;
        },

        async loadLocale(locale) {
            try {
                const response = await fetch(`/static/locales/${locale}.json?v=${APP_VERSION}`);
                if (response.ok) {
                    this.translations = await response.json();
                    this.locale = locale;
                    localStorage.setItem('rss_locale', locale);
                }
            } catch (e) {
                console.error('Failed to load locale:', locale, e);
            }
        },

        // Render markdown to HTML
        renderMarkdown(text) {
            if (!text) return '';
            if (typeof marked !== 'undefined') {
                // Configure marked for safe rendering
                marked.setOptions({
                    breaks: true,  // Convert \n to <br>
                    gfm: true,     // GitHub Flavored Markdown
                });
                return marked.parse(text);
            }
            // Fallback: basic conversion if marked not loaded
            return text
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.+?)\*/g, '<em>$1</em>')
                .replace(/^• /gm, '<li>')
                .replace(/\n/g, '<br>');
        },

        async setLocale(locale) {
            await this.loadLocale(locale);
            // Save to server if logged in
            if (this.token) {
                this.savePreferencesToServer();
            }
        },

        setTheme(theme) {
            this.theme = theme;
            localStorage.setItem('rss_theme', theme);
            this.applyTheme();
            // Save to server if logged in
            if (this.token) {
                this.savePreferencesToServer();
            }
        },

        // AI Settings
        async loadSummaryLanguages() {
            try {
                const response = await fetch(`${API_BASE}/admin/languages`);
                if (response.ok) {
                    this.availableSummaryLanguages = await response.json();
                }
            } catch (e) {
                console.warn('Failed to load summary languages:', e);
            }
        },

        async loadAvailableModels() {
            try {
                const models = await this.fetchApi('/admin/models');
                this.availableModels = models || [];
            } catch (e) {
                console.warn('Failed to load AI models:', e);
                this.availableModels = [];
            }
        },

        setSummaryLanguage(language) {
            this.summaryLanguage = language;
            if (this.token) {
                this.savePreferencesToServer();
            }
        },

        setCerebrasModel(model) {
            this.cerebrasModel = model;
            if (this.token) {
                this.savePreferencesToServer();
            }
        },

        // Toggle accordion section (exclusive - only one open at a time)
        toggleAccordion(section) {
            const wasOpen = this.settingsAccordion[section];
            // Close all
            Object.keys(this.settingsAccordion).forEach(k => {
                this.settingsAccordion[k] = false;
            });
            // Open clicked one if it was closed
            if (!wasOpen) {
                this.settingsAccordion[section] = true;
            }
        },

        // Data settings setters
        setFeedUpdateInterval(value) {
            this.feedUpdateInterval = parseInt(value) || 30;
            if (this.token) this.savePreferencesToServer();
        },

        setMaxPostsPerFeed(value) {
            this.maxPostsPerFeed = parseInt(value) || 500;
            if (this.token) this.savePreferencesToServer();
        },

        setMaxPostAgeDays(value) {
            this.maxPostAgeDays = parseInt(value) || 365;
            if (this.token) this.savePreferencesToServer();
        },

        setMaxUnreadDays(value) {
            this.maxUnreadDays = parseInt(value) || 90;
            if (this.token) this.savePreferencesToServer();
        },

        // Interface settings setters
        setToastTimeout(value) {
            this.toastTimeoutSeconds = parseInt(value) || 2;
            if (this.token) this.savePreferencesToServer();
        },

        setIdleRefresh(value) {
            this.idleRefreshSeconds = parseInt(value) || 180;
            // Update idle timer with new value
            this.resetIdleTimer();
            if (this.token) this.savePreferencesToServer();
        },

        setSuggestionMinTags(value) {
            this.suggestionMinTags = Math.max(1, Math.min(5, parseInt(value) || 3));
            if (this.token) this.savePreferencesToServer();
        },

        setReadingMode(mode) {
            this.readingMode = mode;
            // Close post when switching modes
            if (this.currentPost) {
                this.currentPost = null;
            }
            if (this.token) this.savePreferencesToServer();
        },

        // Split view resize methods
        startResize(e) {
            e.preventDefault();
            this.resizing = true;
            // Bind methods to preserve context
            this._doResize = this.doResize.bind(this);
            this._stopResize = this.stopResize.bind(this);
            // Mouse events
            document.addEventListener('mousemove', this._doResize);
            document.addEventListener('mouseup', this._stopResize);
            // Touch events
            document.addEventListener('touchmove', this._doResize, { passive: false });
            document.addEventListener('touchend', this._stopResize);
            document.addEventListener('touchcancel', this._stopResize);
            // Prevent text selection during drag
            document.body.style.userSelect = 'none';
            document.body.style.cursor = 'row-resize';
        },

        doResize(e) {
            e.preventDefault(); // Prevent scroll/refresh on touch
            const container = document.getElementById('split-container');
            if (!container) return;
            const rect = container.getBoundingClientRect();
            // Handle both mouse and touch events
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;
            let ratio = ((clientY - rect.top) / rect.height) * 100;
            // Clamp between 20% and 80%
            this.splitRatio = Math.min(80, Math.max(20, Math.round(ratio)));
        },

        stopResize() {
            this.resizing = false;
            // Remove mouse events
            document.removeEventListener('mousemove', this._doResize);
            document.removeEventListener('mouseup', this._stopResize);
            // Remove touch events
            document.removeEventListener('touchmove', this._doResize);
            document.removeEventListener('touchend', this._stopResize);
            document.removeEventListener('touchcancel', this._stopResize);
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
            // Save to server
            if (this.token) this.savePreferencesToServer();
        },

        // Save preferences to server (fire and forget)
        async savePreferencesToServer() {
            try {
                await this.fetchApi('/preferences', {
                    method: 'PUT',
                    body: JSON.stringify({
                        locale: this.locale,
                        theme: this.theme,
                        summary_language: this.summaryLanguage,
                        cerebras_model: this.cerebrasModel,
                        feed_update_interval: this.feedUpdateInterval,
                        max_posts_per_feed: this.maxPostsPerFeed,
                        max_post_age_days: this.maxPostAgeDays,
                        max_unread_days: this.maxUnreadDays,
                        toast_timeout_seconds: this.toastTimeoutSeconds,
                        idle_refresh_seconds: this.idleRefreshSeconds,
                        reading_mode: this.readingMode,
                        split_ratio: this.splitRatio,
                        suggestion_min_tags: this.suggestionMinTags,
                    }),
                });
            } catch (e) {
                console.warn('Failed to save preferences to server:', e);
            }
        },

        // Sync preferences after login
        async syncPreferences() {
            try {
                const serverPrefs = await this.fetchApi('/preferences');

                // Apply locale/theme preferences
                if (serverPrefs.locale || serverPrefs.theme) {
                    if (serverPrefs.locale && serverPrefs.locale !== this.locale) {
                        await this.loadLocale(serverPrefs.locale);
                    }
                    if (serverPrefs.theme && serverPrefs.theme !== this.theme) {
                        this.theme = serverPrefs.theme;
                        localStorage.setItem('rss_theme', serverPrefs.theme);
                        this.applyTheme();
                    }
                } else {
                    // Server has no locale/theme - save current localStorage values
                    await this.savePreferencesToServer();
                }

                // Apply AI settings (always from server, with defaults)
                if (serverPrefs.summary_language) {
                    this.summaryLanguage = serverPrefs.summary_language;
                }
                if (serverPrefs.cerebras_model) {
                    this.cerebrasModel = serverPrefs.cerebras_model;
                }

                // Apply data settings (always from server, with defaults)
                if (serverPrefs.feed_update_interval) {
                    this.feedUpdateInterval = serverPrefs.feed_update_interval;
                }
                if (serverPrefs.max_posts_per_feed) {
                    this.maxPostsPerFeed = serverPrefs.max_posts_per_feed;
                }
                if (serverPrefs.max_post_age_days) {
                    this.maxPostAgeDays = serverPrefs.max_post_age_days;
                }
                if (serverPrefs.max_unread_days) {
                    this.maxUnreadDays = serverPrefs.max_unread_days;
                }

                // Apply interface settings (always from server, with defaults)
                if (serverPrefs.toast_timeout_seconds !== null && serverPrefs.toast_timeout_seconds !== undefined) {
                    this.toastTimeoutSeconds = serverPrefs.toast_timeout_seconds;
                }
                if (serverPrefs.idle_refresh_seconds !== null && serverPrefs.idle_refresh_seconds !== undefined) {
                    this.idleRefreshSeconds = serverPrefs.idle_refresh_seconds;
                    this.resetIdleTimer();
                }
                if (serverPrefs.suggestion_min_tags !== null && serverPrefs.suggestion_min_tags !== undefined) {
                    this.suggestionMinTags = serverPrefs.suggestion_min_tags;
                }
                if (serverPrefs.reading_mode) {
                    this.readingMode = serverPrefs.reading_mode;
                }
                if (serverPrefs.split_ratio !== null && serverPrefs.split_ratio !== undefined) {
                    this.splitRatio = serverPrefs.split_ratio;
                }
            } catch (e) {
                console.warn('Failed to sync preferences:', e);
            }
        },

        applyTheme() {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const shouldBeDark = this.theme === 'dark' || (this.theme === 'system' && prefersDark);

            if (shouldBeDark) {
                document.documentElement.classList.add('dark');
            } else {
                document.documentElement.classList.remove('dark');
            }
        },

        // Toast notifications
        showToast(message, type = 'info', autoClose = true) {
            // Clear any existing timeout
            if (this.toast.timeoutId) {
                clearTimeout(this.toast.timeoutId);
            }

            this.toast.message = message;
            this.toast.type = type;
            this.toast.show = true;

            if (autoClose && this.toastTimeoutSeconds > 0) {
                this.toast.timeoutId = setTimeout(() => {
                    this.hideToast();
                }, this.toastTimeoutSeconds * 1000);
            }
        },

        showSuccess(message) {
            this.showToast(message, 'success');
        },

        showError(message) {
            this.showToast(message, 'error');
        },

        showInfo(message) {
            this.showToast(message, 'info');
        },

        hideToast() {
            this.toast.show = false;
        },

        // Translate backend error messages
        translateError(message) {
            const key = `backendErrors.${message.replace(/[^a-zA-Z0-9]/g, '_')}`;
            const translated = this.t(key);
            // If translation exists (not the key itself), return it
            return translated !== key ? translated : message;
        },

        // Custom confirm modal
        showConfirm(message) {
            return new Promise((resolve) => {
                this.confirmModal.message = message;
                this.confirmModal.resolve = resolve;
                this.confirmModal.show = true;
                // Focus OK button after modal renders
                this.$nextTick(() => {
                    const btn = document.getElementById('confirm-ok-btn');
                    if (btn) btn.focus();
                });
            });
        },

        confirmOk() {
            // Don't close modal here - caller manages it via confirmDone()
            if (this.confirmModal.resolve) {
                this.confirmModal.resolve(true);
                this.confirmModal.resolve = null;
            }
        },

        confirmCancel() {
            this.confirmModal.show = false;
            if (this.confirmModal.resolve) {
                this.confirmModal.resolve(false);
                this.confirmModal.resolve = null;
            }
        },

        confirmLoading(message) {
            this.confirmModal.loading = true;
            this.confirmModal.message = message;
        },

        confirmDone() {
            this.confirmModal.show = false;
            this.confirmModal.loading = false;
        },

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
                console.warn('Failed to load config, using defaults');
            }
        },

        // Initialize
        async init() {
            // Load available locales and summary languages from server first (no auth)
            await Promise.all([
                this.loadAvailableLocales(),
                this.loadSummaryLanguages(),
            ]);

            // Detect locale if not in localStorage
            if (!this.locale) {
                this.locale = this.detectBrowserLocale();
            }

            // Load config and translations in parallel
            await Promise.all([
                this.loadConfig(),
                this.loadLocale(this.locale),
            ]);

            // Apply theme and listen for system theme changes
            this.applyTheme();
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
                if (this.theme === 'system') {
                    this.applyTheme();
                }
            });

            // Check for stored token
            const storedToken = sessionStorage.getItem('rss_token');
            if (storedToken) {
                this.token = storedToken;
                await this.loadData();
                await this.syncPreferences();
                // Load AI models (requires auth)
                this.loadAvailableModels();
                this.setupIdleDetection();
            }

            // Setup keyboard shortcuts
            this.setupKeyboardShortcuts();

            // Setup back button handler for modals
            this.setupBackButtonHandler();
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

                // Ignore if in input
                if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') {
                    return;
                }

                // If confirm modal is open, let it handle its own keys
                if (this.confirmModal.show) {
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
                    } else if (this.isKey(e, 'r') && e.shiftKey) {
                        this.regenerateSummary();
                        return;
                    } else if (this.isKey(e, 'r') && !e.shiftKey) {
                        this.refreshFeeds();
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
                } else if (this.isKey(e, 'r')) {
                    this.refreshFeeds();
                } else if (this.isKey(e, 'x')) {
                    this.toggleSelectMode();
                } else if (this.isKey(e, 'a')) {
                    this.markAllRead();
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

                const data = await response.json();
                this.token = data.token;
                sessionStorage.setItem('rss_token', this.token);
                this.password = '';
                await this.loadData();
                await this.syncPreferences();
                // Load AI models (requires auth)
                this.loadAvailableModels();
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
                // Ignore logout errors
            }
            this.token = null;
            sessionStorage.removeItem('rss_token');
            this.feeds = [];
            this.categories = [];
            this.posts = [];
            this.currentPost = null;
        },

        // API helper
        async fetchApi(endpoint, options = {}) {
            const headers = {
                'Content-Type': 'application/json',
                ...options.headers,
            };

            if (this.token) {
                headers['Authorization'] = `Bearer ${this.token}`;
            }

            const response = await fetch(`${API_BASE}${endpoint}`, {
                ...options,
                headers,
            });

            if (response.status === 401) {
                this.logout();
                throw new Error(this.t('errors.sessionExpired'));
            }

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || this.t('errors.requestFailed'));
            }

            // Handle 204 No Content
            if (response.status === 204) {
                return null;
            }

            return response.json();
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
            if (this.loading) return;

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

                const data = await this.fetchApi(`/posts?${params}`);

                if (reset) {
                    this.posts = data.posts;
                } else {
                    this.posts = [...this.posts, ...data.posts];
                }

                this.hasMore = data.has_more || false;
                this.offset += data.posts.length;

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
            } catch (error) {
                console.error('Failed to load posts:', error);
            } finally {
                this.loading = false;
            }
        },

        async checkHealth() {
            try {
                const data = await this.fetchApi('/admin/status');
                this.healthWarning = data.health_warning;
            } catch (e) {
                // Ignore health check errors
            }
        },

        // Filters
        setFilter(type, id = null) {
            this.filter = type;
            this.filterId = id;
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

        // Post operations
        async openPost(post) {
            // Set loading state FIRST to prevent flash of old content
            this.loadingContent = true;

            // Clear previous content to avoid showing stale data
            this.currentPost = {
                ...post,
                full_content: null,
                summary_pt: null,
                summary_status: 'pending',
            };

            // Push state for back button support (only in fullscreen mode)
            if (!this.isSplitMode) {
                history.pushState({ modal: 'post', postId: post.id }, '');
            }

            // Find index
            const index = this.getPostIndex(post.id);
            if (index >= 0) {
                this.selectedIndex = index;
            }

            // Mark as read
            if (!post.is_read) {
                await this.markPostRead(post, true);
            }

            // Load full post detail (includes full_content and summary_pt)
            try {
                const data = await this.fetchApi(`/posts/${post.id}`);
                // Clean non-breaking spaces from text fields
                if (data.full_content) data.full_content = this.cleanText(data.full_content);
                if (data.summary_pt) data.summary_pt = this.cleanText(data.summary_pt);
                if (data.one_line_summary) data.one_line_summary = this.cleanText(data.one_line_summary);

                this.currentPost = { ...this.currentPost, ...data };
                this.updatePost(post.id, {
                    full_content: data.full_content,
                    summary_pt: data.summary_pt,
                    one_line_summary: data.one_line_summary,
                    translated_title: data.translated_title,
                });
            } catch (e) {
                console.error('Failed to load post detail:', e);
                this.currentPost.summary_status = 'failed';
            } finally {
                this.loadingContent = false;
            }
        },

        closePost() {
            if (this.currentPost) {
                // Close modal directly
                this.currentPost = null;
                // Go back in history only in fullscreen mode
                if (!this.isSplitMode && history.state && history.state.modal === 'post') {
                    history.back();
                }
            }
        },

        async toggleRead(post) {
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

                // Update feed unread count
                const feed = this.feeds.find(f => f.id === post.feed_id);
                if (feed) {
                    feed.unread_count = Math.max(0, (feed.unread_count || 0) + (isRead ? -1 : 1));
                }

                // Update suggested count if this was a suggested post
                if (post.is_suggested) {
                    if (isRead) {
                        this.suggestedCount = Math.max(0, this.suggestedCount - 1);
                    } else {
                        this.suggestedCount++;
                    }
                }
            } catch (error) {
                console.error('Failed to mark post read:', error);
            }
        },

        async toggleStar(post) {
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

        async markAllRead() {
            // Get unread posts currently visible in the interface
            // This ensures we only mark posts the user has seen, not new ones
            // that may have arrived via background refresh
            const visibleUnreadIds = this.posts
                .filter(p => !p.is_read)
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
            } else {
                contextName = this.t('confirm.allPosts');
            }

            // Ask for confirmation
            const msg = this.t('confirm.markAllRead')
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

        scrollToSelected() {
            // Use setTimeout to ensure DOM is fully updated (more reliable on mobile)
            setTimeout(() => {
                const el = document.querySelector(`[data-index="${this.selectedIndex}"]`);
                if (!el) return;

                try {
                    el.scrollIntoView({ block: 'nearest', behavior: 'auto' });
                } catch (e) {
                    el.scrollIntoView(false);
                }
            }, 50);
        },

        nextPost() {
            if (this.loadingContent) return;
            const idx = this.getCurrentPostIndex();
            if (idx >= 0 && idx < this.posts.length - 1) {
                this.selectedIndex = idx + 1;
                this.openPost(this.posts[idx + 1]);
                this.scrollToSelected();
            }
        },

        prevPost() {
            if (this.loadingContent) return;
            const idx = this.getCurrentPostIndex();
            if (idx > 0) {
                this.selectedIndex = idx - 1;
                this.openPost(this.posts[idx - 1]);
                this.scrollToSelected();
            }
        },

        canGoPrev() {
            return this.getCurrentPostIndex() > 0;
        },

        canGoNext() {
            const idx = this.getCurrentPostIndex();
            return idx >= 0 && idx < this.posts.length - 1;
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

            const postIds = Array.from(this.selectedPosts);

            try {
                await this.fetchApi('/posts/mark-read', {
                    method: 'POST',
                    body: JSON.stringify({ post_ids: postIds }),
                });

                // Update local state
                this.posts.forEach(p => {
                    if (this.selectedPosts.has(p.id)) {
                        p.is_read = true;
                    }
                });

                // Update feed unread counts
                await this.loadFeeds();

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

        // Regenerate AI Summary
        async regenerateSummary() {
            if (!this.currentPost || this.regeneratingSummary) return;

            this.regeneratingSummary = true;

            try {
                const data = await this.fetchApi(`/posts/${this.currentPost.id}/regenerate-summary`, {
                    method: 'POST',
                });

                const updates = {
                    summary_pt: this.cleanText(data.summary_pt),
                    one_line_summary: this.cleanText(data.one_line_summary),
                    translated_title: data.translated_title,
                    summary_status: 'ready',
                };

                this.currentPost = { ...this.currentPost, ...updates };
                this.updatePost(this.currentPost.id, updates);
            } catch (error) {
                console.error('Failed to regenerate summary:', error);
                this.showError(this.t('errors.regenerateSummary') + ': ' + this.translateError(error.message));
            } finally {
                this.regeneratingSummary = false;
            }
        },

        // Text cleaning
        cleanText(text) {
            if (!text) return text;
            // Replace all types of non-breaking spaces with regular spaces
            // \u00A0 = NO-BREAK SPACE
            // \u202F = NARROW NO-BREAK SPACE
            // \u2007 = FIGURE SPACE
            // \u2060 = WORD JOINER
            return text.replace(/[\u00A0\u202F\u2007\u2060]/g, ' ').replace(/&nbsp;/g, ' ');
        },

        // Formatting
        formatDate(dateStr) {
            if (!dateStr) return '';

            const MINUTE = 60000;
            const HOUR = 3600000;
            const DAY = 86400000;
            const WEEK = 604800000;

            const date = new Date(dateStr);
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

        // Settings - Categories
        async createCategory() {
            if (!this.newCategoryName.trim()) return;
            this.savingCategory = true;
            try {
                await this.fetchApi('/categories', {
                    method: 'POST',
                    body: JSON.stringify({ name: this.newCategoryName.trim() }),
                });
                this.newCategoryName = '';
                await this.loadCategories();
            } catch (error) {
                console.error('Failed to create category:', error);
                this.showError(this.t('errors.createCategory') + ': ' + this.translateError(error.message));
            } finally {
                this.savingCategory = false;
            }
        },

        startEditCategory(category) {
            this.editingCategory = { ...category };
        },

        cancelEditCategory() {
            this.editingCategory = null;
        },

        async saveCategory() {
            if (!this.editingCategory || !this.editingCategory.name.trim()) return;
            this.savingCategory = true;
            try {
                await this.fetchApi(`/categories/${this.editingCategory.id}`, {
                    method: 'PUT',
                    body: JSON.stringify({ name: this.editingCategory.name.trim() }),
                });
                this.editingCategory = null;
                await this.loadCategories();
            } catch (error) {
                console.error('Failed to save category:', error);
                this.showError(this.t('errors.saveCategory') + ': ' + this.translateError(error.message));
            } finally {
                this.savingCategory = false;
            }
        },

        async deleteCategory(category) {
            const feedCount = this.feeds.filter(f => f.category_id === category.id).length;
            const msg = feedCount > 0
                ? this.t('confirm.deleteCategoryWithFeeds').replace('{name}', category.name).replace('{count}', feedCount)
                : this.t('confirm.deleteCategory').replace('{name}', category.name);
            if (!await this.showConfirm(msg)) return;

            this.confirmLoading(this.t('confirm.deleting'));
            try {
                await this.fetchApi(`/categories/${category.id}`, { method: 'DELETE' });
                await Promise.all([this.loadCategories(), this.loadFeeds()]);
            } catch (error) {
                console.error('Failed to delete category:', error);
                this.showError(this.t('errors.deleteCategory') + ': ' + this.translateError(error.message));
            } finally {
                this.confirmDone();
            }
        },

        // Settings - Feeds
        async createFeed() {
            if (!this.newFeed.url.trim()) return;
            this.savingFeed = true;

            let feedUrl = this.newFeed.url.trim();

            try {
                // Try to discover feed if URL doesn't look like a feed
                if (!feedUrl.match(/\.(xml|rss|atom)$/i) && !feedUrl.includes('/feed')) {
                    try {
                        const discovered = await this.fetchApi(`/feeds/discover?url=${encodeURIComponent(feedUrl)}`, {
                            method: 'POST',
                        });
                        feedUrl = discovered.feed_url;
                    } catch (discoverError) {
                        // If discovery fails with 404, show specific message
                        if (discoverError.message.includes('No RSS/Atom feed found')) {
                            this.showError(this.t('errors.noFeedFound'));
                            return;
                        }
                        // For other errors, try the original URL anyway
                    }
                }

                const feed = await this.fetchApi('/feeds', {
                    method: 'POST',
                    body: JSON.stringify({
                        url: feedUrl,
                        category_id: this.newFeed.category_id || null,
                    }),
                });
                this.newFeed = { url: '', category_id: '' };
                await this.loadFeeds();
                // Reload posts to show new content
                await this.loadPosts(true);
                // Show success message
                if (feed.unread_count > 0) {
                    this.showSuccess(this.t('success.feedAdded').replace('{count}', feed.unread_count));
                }
            } catch (error) {
                console.error('Failed to create feed:', error);
                this.showError(this.t('errors.createFeed') + ': ' + this.translateError(error.message));
            } finally {
                this.savingFeed = false;
            }
        },

        startEditFeed(feed) {
            this.editingFeed = { ...feed };
        },

        cancelEditFeed() {
            this.editingFeed = null;
        },

        async saveFeed() {
            if (!this.editingFeed) return;
            this.savingFeed = true;
            try {
                await this.fetchApi(`/feeds/${this.editingFeed.id}`, {
                    method: 'PUT',
                    body: JSON.stringify({
                        url: this.editingFeed.url,
                        title: this.editingFeed.title,
                        category_id: this.editingFeed.category_id || null,
                    }),
                });
                this.editingFeed = null;
                await this.loadFeeds();
            } catch (error) {
                console.error('Failed to save feed:', error);
                this.showError(this.t('errors.saveFeed') + ': ' + this.translateError(error.message));
            } finally {
                this.savingFeed = false;
            }
        },

        async refreshFeed(feedId) {
            if (this.refreshingFeed) return;
            this.refreshingFeed = true;
            try {
                const result = await this.fetchApi(`/feeds/${feedId}/refresh`, { method: 'POST' });
                await this.loadFeeds();
                await this.loadPosts(true);
                const msg = this.t('feeds.refreshResult')
                    .replace('{new}', result.new_posts)
                    .replace('{skipped}', result.skipped_duplicates);
                this.showSuccess(msg);
            } catch (error) {
                console.error('Failed to refresh feed:', error);
                this.showError(this.t('errors.refreshFeed') + ': ' + this.translateError(error.message));
            } finally {
                this.refreshingFeed = false;
            }
        },

        async deleteFeed(feed) {
            if (!await this.showConfirm(this.t('confirm.deleteFeed').replace('{title}', feed.title))) return;

            this.confirmLoading(this.t('confirm.deleting'));
            try {
                await this.fetchApi(`/feeds/${feed.id}`, { method: 'DELETE' });
                await this.loadFeeds();
                if (this.filter === 'feed' && this.filterId === feed.id) {
                    this.setFilter('unread');
                }
            } catch (error) {
                console.error('Failed to delete feed:', error);
                this.showError(this.t('errors.deleteFeed') + ': ' + this.translateError(error.message));
            } finally {
                this.confirmDone();
            }
        },

        async handleOpmlFile(event) {
            const file = event.target.files[0];
            if (!file) return;

            this.importingOpml = true;
            this.opmlResult = null;

            try {
                const formData = new FormData();
                formData.append('file', file);

                const response = await fetch('/api/feeds/import-opml', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${this.token}`,
                    },
                    body: formData,
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || this.t('errors.generic'));
                }

                this.opmlResult = await response.json();

                // Reload feeds and categories
                await this.loadFeeds();
                await this.loadCategories();

            } catch (error) {
                console.error('Failed to import OPML:', error);
                this.showError(this.t('errors.importOpml') + ': ' + this.translateError(error.message));
            } finally {
                this.importingOpml = false;
                // Reset file input
                event.target.value = '';
            }
        },

        openSettings() {
            this.showSettings = true;
            history.pushState({ modal: 'settings' }, '');
        },

        closeSettings() {
            if (this.showSettings) {
                history.back();
            }
        },

        _closeSettingsInternal() {
            this.showSettings = false;
            this.editingCategory = null;
            this.editingFeed = null;
            this.newCategoryName = '';
            this.newFeed = { url: '', category_id: '' };
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

            // Refresh feed unread counts silently
            try {
                await this.loadFeeds();
            } catch (e) {
                // Ignore errors on idle refresh
            }

            // Restart timer for next idle check
            this.resetIdleTimer();
        },
    };
}
