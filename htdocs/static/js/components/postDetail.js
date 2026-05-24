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

    _ABBREVIATIONS: [
        'p.ex.', 'i.e.', 'e.g.', 'U.S.', 'U.K.',
        'etc.', 'vs.',
        'Inc.', 'Ltd.', 'Corp.', 'Co.',
        'Dr.', 'Dra.', 'Sr.', 'Sra.', 'Prof.', 'Profa.', 'Jr.',
        'EUA.', 'nº.', 'ed.', 'vol.', 'cap.',
    ],

    splitIntoParagraphs(text) {
        if (!text) return text;
        // Already has paragraph breaks — leave as-is
        if (/\n\s*\n/.test(text)) return text;

        const PLACEHOLDER = '\x00';
        const abbrPattern = new RegExp(
            '\\b(' + this._ABBREVIATIONS
                .sort((a, b) => b.length - a.length)
                .map(a => a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
                .join('|') + ')',
            'g'
        );

        const masked = text.replace(abbrPattern, m => m.replaceAll('.', PLACEHOLDER));
        const sentences = masked.split(/(?<=[.!?])\s+(?=[A-ZÀ-ÝÇ0-9])/);

        return sentences
            .map(s => s.replaceAll(PLACEHOLDER, '.').trim())
            .filter(Boolean)
            .join('\n\n');
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
            if (data.summary_pt) data.summary_pt = this.splitIntoParagraphs(this.cleanText(data.summary_pt));
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
                summary_pt: this.splitIntoParagraphs(this.cleanText(data.summary_pt)),
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
