/**
 * PostDetail mixin — post viewing, navigation, summary, export
 *
 * Spread into app() via ...postDetailMixin so `this` is the Alpine component.
 * Dependencies from app: posts, selectedIndex, feeds, fetchApi(), updatePost(),
 *   markPostRead(), scrollToSelected(), showToast(), showError(), t(),
 *   translateError(), isSplitMode, getPostIndex(), getFeedTitle()
 */
const postDetailMixin = {
    // State
    currentPost: null,
    loadingContent: false,
    regeneratingSummary: false,
    readerResizing: false,
    summaryWidthPercent: parseFloat(localStorage.getItem('risos_summary_width') || '33.33'),
    showAssistantModal: false,
    relatedPosts: [],
    selectedRelatedPosts: new Set(),
    assistantSummary: null,
    assistantLoading: false,
    assistantGenerating: false,
    assistantIncludeRead: true,
    assistantIncludeUnread: true,
    assistantMarkingRead: false,

    // Helpers
    getCurrentPostIndex() {
        return this.currentPost ? this.getPostIndex(this.currentPost.id) : -1;
    },

    cleanText(text) {
        if (!text) return text;
        // Replace all types of non-breaking spaces with regular spaces
        // \u00A0 = NO-BREAK SPACE
        // \u202F = NARROW NO-BREAK SPACE
        // \u2007 = FIGURE SPACE
        // \u2060 = WORD JOINER
        return text.replace(/[\u00A0\u202F\u2007\u2060]/g, ' ').replace(/&nbsp;/g, ' ');
    },

    // Open / close
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

        // Mark as read (skip if protected)
        if (!post.is_read && !post.keep_unread) {
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

    // Navigation
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

    // Summary operations
    async toggleSkipSummary() {
        if (!this.currentPost) return;
        try {
            const data = await this.fetchApi(`/posts/${this.currentPost.id}/skip-summary`, {
                method: 'POST',
            });
            this.currentPost = { ...this.currentPost, skip_summary: data.skip_summary };
            this.updatePost(this.currentPost.id, { skip_summary: data.skip_summary });
        } catch (error) {
            console.error('Failed to toggle skip summary:', error);
        }
    },

    async regenerateSummary() {
        if (!this.currentPost || this.regeneratingSummary) return;

        if (this.currentPost.skip_summary) {
            this.showToast(this.t('modal.cannotRegenerateSkipped'), 'error');
            return;
        }

        this.regeneratingSummary = true;

        try {
            const data = await this.fetchApi(`/posts/${this.currentPost.id}/regenerate-summary`, {
                method: 'POST',
            });

            const updates = {
                summary_pt: this.cleanText(data.summary_pt),
                one_line_summary: this.cleanText(data.one_line_summary),
                translated_title: data.translated_title,
                tags: data.tags || [],
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

    // Copy to Clipboard
    async copySummaryToClipboard() {
        if (!this.currentPost || !this.currentPost.summary_pt) return;
        try {
            await navigator.clipboard.writeText(this.currentPost.summary_pt);
            this.showToast(this.t('modal.summaryCopied'));
        } catch (err) {
            console.error('Failed to copy summary:', err);
            this.showToast(this.t('errors.copyFailed'), 'error');
        }
    },

    // Horizontal split view reading pane resize
    startReaderResize(e) {
        e.preventDefault();
        this.readerResizing = true;
        this._doReaderResize = this.doReaderResize.bind(this);
        this._stopReaderResize = this.stopReaderResize.bind(this);
        document.addEventListener('mousemove', this._doReaderResize);
        document.addEventListener('mouseup', this._stopReaderResize);
        document.addEventListener('touchmove', this._doReaderResize, { passive: false });
        document.addEventListener('touchend', this._stopReaderResize);
        document.addEventListener('touchcancel', this._stopReaderResize);
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'col-resize';
    },

    doReaderResize(e) {
        e.preventDefault();
        const container = document.getElementById('post-reader-two-columns');
        if (!container) return;
        const rect = container.getBoundingClientRect();
        const clientX = e.touches ? e.touches[0].clientX : e.clientX;
        
        const relativeX = clientX - rect.left;
        const leftWidthPercent = (relativeX / rect.width) * 100;
        let rightWidthPercent = 100 - leftWidthPercent;
        
        // Limits: min 20% and max 60% for the AI Summary column to keep visual balance
        this.summaryWidthPercent = Math.min(60, Math.max(20, Math.round(rightWidthPercent * 100) / 100));
    },

    stopReaderResize() {
        this.readerResizing = false;
        document.removeEventListener('mousemove', this._doReaderResize);
        document.removeEventListener('mouseup', this._stopReaderResize);
        document.removeEventListener('touchmove', this._doReaderResize);
        document.removeEventListener('touchend', this._stopReaderResize);
        document.removeEventListener('touchcancel', this._stopReaderResize);
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        localStorage.setItem('risos_summary_width', this.summaryWidthPercent.toString());
    },

    // Assistant / Sparkle methods
    async openAssistant() {
        if (!this.currentPost) return;
        this.showAssistantModal = true;
        this.assistantIncludeRead = true;
        this.assistantIncludeUnread = true;
        this.assistantSummary = null;
        await this.loadRelatedPosts();
    },

    async loadRelatedPosts() {
        if (!this.currentPost) return;
        this.assistantLoading = true;
        this.relatedPosts = [];
        this.selectedRelatedPosts = new Set();
        this.assistantSummary = null; // Limpa o resumo anterior ao alterar os filtros
        try {
            const params = new URLSearchParams({
                include_read: this.assistantIncludeRead,
                include_unread: this.assistantIncludeUnread
            });
            const data = await this.fetchApi(`/posts/${this.currentPost.id}/related?${params.toString()}`);
            this.relatedPosts = data.posts || [];
            
            // Cria um novo Set e atribui de forma atômica para forçar a reatividade do Alpine
            const newSelection = new Set();
            this.relatedPosts.forEach(p => newSelection.add(p.id));
            this.selectedRelatedPosts = newSelection;
        } catch (e) {
            console.error('Failed to load related posts:', e);
            this.showError(this.t('errors.loadRelatedPosts') + ': ' + this.translateError(e.message));
        } finally {
            this.assistantLoading = false;
        }
    },

    toggleRelatedPostSelection(postId) {
        if (this.selectedRelatedPosts.has(postId)) {
            this.selectedRelatedPosts.delete(postId);
        } else {
            this.selectedRelatedPosts.add(postId);
        }
        this.selectedRelatedPosts = new Set(this.selectedRelatedPosts);
    },

    toggleAllRelatedPosts() {
        if (this.selectedRelatedPosts.size === this.relatedPosts.length) {
            this.selectedRelatedPosts.clear();
        } else {
            this.relatedPosts.forEach(p => this.selectedRelatedPosts.add(p.id));
        }
        this.selectedRelatedPosts = new Set(this.selectedRelatedPosts);
    },

    async processRelatedPosts() {
        if (this.selectedRelatedPosts.size === 0 || this.assistantGenerating) return;
        this.assistantGenerating = true;
        this.assistantSummary = null;
        try {
            const postIds = Array.from(this.selectedRelatedPosts);
            // Inclui automaticamente o post de origem na consolidação
            if (this.currentPost && !postIds.includes(this.currentPost.id)) {
                postIds.push(this.currentPost.id);
            }
            const data = await this.fetchApi('/posts/related-summary', {
                method: 'POST',
                body: JSON.stringify({ post_ids: postIds }),
            });
            this.assistantSummary = data.summary;
        } catch (e) {
            console.error('Failed to generate consolidated summary:', e);
            this.showError(this.t('errors.generateConsolidatedSummary') + ': ' + this.translateError(e.message));
        } finally {
            this.assistantGenerating = false;
        }
    },

    async copyAssistantSummary() {
        if (!this.assistantSummary) return;
        try {
            await navigator.clipboard.writeText(this.assistantSummary);
            this.showToast(this.t('modal.summaryCopied'));
        } catch (err) {
            console.error('Failed to copy consolidated summary:', err);
            this.showToast(this.t('errors.copyFailed'), 'error');
        }
    },

    async markProcessedAsRead() {
        if (this.selectedRelatedPosts.size === 0 || this.assistantMarkingRead) return;
        this.assistantMarkingRead = true;
        try {
            const postIds = Array.from(this.selectedRelatedPosts);
            // Também inclui o post de origem ao marcar como lidos
            if (this.currentPost && !postIds.includes(this.currentPost.id)) {
                postIds.push(this.currentPost.id);
            }
            await this.fetchApi('/posts/mark-read', {
                method: 'POST',
                body: JSON.stringify({ post_ids: postIds }),
            });

            // Atualiza o estado is_read local de cada post na lista de posts principal
            postIds.forEach(id => {
                const localPost = this.posts.find(p => p.id === id);
                if (localPost) {
                    localPost.is_read = true;
                }
            });

            this.showToast(this.t('modal.markedAsReadSuccess') || 'Posts marcados como lidos!');
        } catch (e) {
            console.error('Failed to mark posts as read:', e);
            this.showToast(this.t('errors.markReadFailed') || 'Erro ao marcar posts como lidos', 'error');
        } finally {
            this.assistantMarkingRead = false;
        }
    },

    // Export
    exportPostAsMarkdown() {
        const post = this.currentPost;
        if (!post) return;

        const esc = s => (s || '').replace(/"/g, '\\"');
        const meta = [];
        meta.push(`title: "${esc(post.title || 'Untitled')}"`);
        if (post.translated_title && post.translated_title !== post.title) {
            meta.push(`translated_title: "${esc(post.translated_title)}"`);
        }
        meta.push(`feed: "${esc(this.getFeedTitle(post.feed_id))}"`);
        const date = post.published_at || post.fetched_at;
        if (date) meta.push(`date: ${date.slice(0, 16).replace('T', ' ')}`);
        if (post.url) meta.push(`url: ${post.url}`);
        const tags = (post.tags || []);
        if (tags.length) meta.push(`tags: [${tags.join(', ')}]`);

        const lines = ['---', ...meta, '---', ''];
        if (post.one_line_summary) lines.push('## Summary', '', post.one_line_summary, '');
        if (post.summary_pt) lines.push(post.summary_pt, '');
        const originalContent = post.full_content || post.content;
        if (originalContent) lines.push('## Original Content', '', originalContent, '');

        const blob = new Blob([lines.join('\n')], { type: 'text/markdown' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = (post.title || 'post').replace(/[^a-zA-Z0-9\-_ ]/g, '').replace(/\s+/g, '-').slice(0, 80) + '.md';
        a.click();
        URL.revokeObjectURL(a.href);
    },
};
