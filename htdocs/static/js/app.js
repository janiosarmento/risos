/**
 * Risos - Alpine.js Application
 */

const APP_VERSION = '20260105c';
const API_BASE = '/api';

function app() {
    return {
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
        showReadPosts: false,
        selectedPosts: new Set(),
        selectMode: false,
        collapsedCategories: new Set(JSON.parse(localStorage.getItem('rss_collapsed_categories') || '[]')),
        sidebarOpen: false,
        lastNavMode: 'posts', // 'posts' (J/K) or 'sidebar' ([/])
        lastFeedNavIndex: 0, // Last position in feed navigation (for [/])

        // Settings
        showSettings: false,
        settingsTab: 'categories',
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
        locale: localStorage.getItem('rss_locale') || 'pt-BR',
        translations: {},
        availableLocales: [
            { code: 'pt-BR', name: 'Português (Brasil)' },
            { code: 'en-US', name: 'English (US)' }
        ],

        // Theme
        theme: localStorage.getItem('rss_theme') || 'system',
        availableThemes: [
            { value: 'system', labelKey: 'settings.themeSystem' },
            { value: 'light', labelKey: 'settings.themeLight' },
            { value: 'dark', labelKey: 'settings.themeDark' }
        ],

        // Computed
        get totalUnread() {
            return this.feeds.reduce((sum, f) => sum + (f.unread_count || 0), 0);
        },

        starredCount: 0,

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
            const listPost = this.getPostById(id);
            if (listPost) {
                Object.assign(listPost, updates);
            }
            if (this.currentPost?.id === id) {
                Object.assign(this.currentPost, updates);
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
        },

        setTheme(theme) {
            this.theme = theme;
            localStorage.setItem('rss_theme', theme);
            this.applyTheme();
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

                // If post modal is open
                if (this.currentPost) {
                    if (e.key === 'Escape') {
                        this.closePost();
                    } else if (this.isKey(e, 'm')) {
                        this.toggleRead(this.currentPost);
                    } else if (this.isKey(e, 's')) {
                        this.toggleStar(this.currentPost);
                    } else if (this.isKey(e, 'r')) {
                        this.regenerateSummary();
                    } else if (this.isKey(e, 'j')) {
                        this.nextPost();
                    } else if (this.isKey(e, 'k')) {
                        this.prevPost();
                    }
                    return;
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

            // Starred (if has items)
            if (this.starredCount > 0) {
                items.push({ type: 'starred' });
            }

            // Unread
            items.push({ type: 'unread' });

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
                if (item.type === 'starred' && this.filter === 'starred') return true;
                if (item.type === 'unread' && this.filter === 'unread') return true;
                if (item.type === 'category' && this.filter === 'category' && this.filterId === item.id) return true;
                if (item.type === 'feed' && this.filter === 'feed' && this.filterId === item.id) return true;
                return false;
            });
        },

        navigateToItem(item) {
            if (item.type === 'starred') {
                this.setFilter('starred');
            } else if (item.type === 'unread') {
                this.setFilter('unread');
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
                const targetIndex = Math.min(this.lastFeedNavIndex, items.length - 1);
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
                this.loadStarredCount(),
            ]);
            await this.loadPosts(true);
            this.checkHealth();
        },

        async loadStarredCount() {
            try {
                const data = await this.fetchApi('/posts?starred_only=true&limit=1');
                this.starredCount = data.total || 0;
            } catch (error) {
                console.error('Failed to load starred count:', error);
            }
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

                // Apply starred filter (ignores other filters)
                if (this.filter === 'starred') {
                    params.set('starred_only', 'true');
                } else {
                    // Apply unread filter unless showing all
                    if (!this.showReadPosts) {
                        params.set('unread_only', 'true');
                    }

                    // Apply feed/category filter
                    if (this.filter === 'feed') {
                        params.set('feed_id', this.filterId);
                    } else if (this.filter === 'category') {
                        params.set('category_id', this.filterId);
                    }
                }

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

            // Push state for back button support
            history.pushState({ modal: 'post', postId: post.id }, '');

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
                // Also go back in history if we have a state for this modal
                if (history.state && history.state.modal === 'post') {
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
                });

                // Update starred count
                if (data.is_starred === true) {
                    this.starredCount++;
                } else {
                    this.starredCount = Math.max(0, this.starredCount - 1);
                }
            } catch (error) {
                console.error('Failed to toggle star:', error);
            }
        },

        async markAllRead() {
            // Determine context and count
            let unreadCount = 0;
            let contextName = '';
            const body = {};

            if (this.filter === 'feed') {
                body.feed_id = this.filterId;
                const feed = this.feeds.find(f => f.id === this.filterId);
                unreadCount = feed?.unread_count || 0;
                contextName = feed?.title || 'feed';
            } else if (this.filter === 'category') {
                body.category_id = this.filterId;
                const category = this.categories.find(c => c.id === this.filterId);
                unreadCount = this.getCategoryUnread(this.filterId);
                contextName = category?.name || this.t('settings.tabs.categories');
            } else {
                // All posts
                unreadCount = this.totalUnread;
                contextName = this.t('confirm.allPosts');
            }

            if (unreadCount === 0) return;

            // Ask for confirmation
            const msg = this.t('confirm.markAllRead')
                .replace('{count}', unreadCount)
                .replace('{context}', contextName);

            if (!await this.showConfirm(msg)) return;

            // Show loading state in modal
            this.confirmLoading(this.t('confirm.markingAsRead'));

            try {
                await this.fetchApi('/posts/mark-read', {
                    method: 'POST',
                    body: JSON.stringify(body),
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
                    await this.loadStarredCount();
                    await this.loadPosts(true);
                    this.showSuccess(this.t('refresh.newPosts').replace('{count}', totalNew));
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
            }
        },

        selectPrev() {
            if (this.selectedIndex > 0) {
                this.selectedIndex--;
                this.scrollToSelected();
            }
        },

        scrollToSelected() {
            const el = document.querySelector(`[data-index="${this.selectedIndex}"]`);
            if (el) {
                el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
            }
        },

        nextPost() {
            if (this.loadingContent) return;
            const idx = this.getCurrentPostIndex();
            if (idx >= 0 && idx < this.posts.length - 1) {
                this.openPost(this.posts[idx + 1]);
            }
        },

        prevPost() {
            if (this.loadingContent) return;
            const idx = this.getCurrentPostIndex();
            if (idx > 0) {
                this.openPost(this.posts[idx - 1]);
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
                if (!this.showReadPosts) {
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
                await this.loadStarredCount();
            } catch (e) {
                // Ignore errors on idle refresh
            }

            // Restart timer for next idle check
            this.resetIdleTimer();
        },
    };
}
