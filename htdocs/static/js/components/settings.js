/**
 * Settings mixin — settings panel, category/feed CRUD, OPML, AI settings,
 * tag merge/purge, topic management, preference setters, sync, resize
 *
 * Spread into app() via ...settingsMixin so `this` is the Alpine component.
 * Dependencies from app: feeds, categories, topics, filter, filterId, token,
 *   fetchApi(), loadFeeds(), loadCategories(), loadPosts(), loadTopics(),
 *   showToast(), showError(), showSuccess(), showConfirm(), confirmLoading(),
 *   confirmDone(), t(), translateError(), loadLocale(), applyTheme(),
 *   setFilter(), resetIdleTimer(), topicsExpanded, tagFilter, selectedTopicId,
 *   loadPopularTags(), topTagsExpanded
 */
const settingsMixin = {
    // --- State ---
    resizing: false, // true while dragging the split-view resize handle
    showSettings: false,
    settingsTab: 'categories',
    settingsAccordion: { appearance: true, ai: false, data: false, interface: false, tagMerge: false },

    // Category CRUD
    newCategoryName: '',
    editingCategory: null,
    savingCategory: false,

    // Feed CRUD
    newFeed: { url: '', category_id: '' },
    editingFeed: null,
    savingFeed: false,

    // OPML
    importingOpml: false,
    opmlResult: null,

    // Topic management (in settings)
    topicSuggestions: null,
    suggestingTopics: false,
    editingTopic: null,
    editingTopicName: '',
    newTopicName: '',
    suggestingTagsForTopicId: null,
    // Tag drag-and-drop between topics
    dragTagName: null,
    dragTagFromTopicId: null,
    dragOverTopicId: null,
    dragTagCopy: false,

    // Tag merge
    mergeOffset: 0,
    mergeBatchSize: 100,
    mergeGroups: [],
    mergeTotalTags: 0,
    mergeSuggesting: false,
    mergeApplying: false,

    // Tag purge
    purgeMaxCount: 1,
    purgeBreakdowns: [],
    purgeTotalTags: 0,
    purgeSample: [],
    purgeLoading: false,
    purgingTags: false,

    // --- Computed ---
    opmlResultText() {
        if (!this.opmlResult) return '';
        const { imported, skipped, errors } = this.opmlResult;
        let text = `${imported} ${this.t('opml.imported')}`;
        if (skipped > 0) text += `, ${skipped} ${this.t('opml.duplicates')}`;
        if (errors?.length > 0) text += `, ${errors.length} ${this.t('opml.errors')}`;
        return text;
    },

    blockedTermsSorted() {
        if (!this.blockedTerms) return '';
        const lines = this.blockedTerms.split('\n').filter(l => l.trim());
        return lines.sort().join('\n');
    },

    // --- Settings panel open/close ---
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
        // Auto-save AI settings (prompts/keys) on close if logged in
        if (this.token) {
            this.saveAiSettings();
        }
        this.showSettings = false;
        this.editingCategory = null;
        this.editingFeed = null;
        this.newCategoryName = '';
        this.newFeed = { url: '', category_id: '' };
    },

    toggleAccordion(section) {
        const wasOpen = this.settingsAccordion[section];
        Object.keys(this.settingsAccordion).forEach(k => {
            this.settingsAccordion[k] = false;
        });
        if (!wasOpen) {
            this.settingsAccordion[section] = true;
        }
    },

    // --- Category CRUD ---
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

    // --- Feed CRUD ---
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
                    if (discoverError.message.includes('No RSS/Atom feed found')) {
                        this.showError(this.t('errors.noFeedFound'));
                        return;
                    }
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
            await this.loadPosts(true);
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
            if (this.topicsExpanded) this.loadTopics();
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

    // --- OPML ---
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
            await this.loadFeeds();
            await this.loadCategories();
        } catch (error) {
            console.error('Failed to import OPML:', error);
            this.showError(this.t('errors.importOpml') + ': ' + this.translateError(error.message));
        } finally {
            this.importingOpml = false;
            event.target.value = '';
        }
    },

    async exportOpml() {
        try {
            const response = await fetch(`${API_BASE}/feeds/export-opml`, {
                headers: { 'Authorization': `Bearer ${this.token}` },
            });
            if (!response.ok) throw new Error('Export failed');
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'feeds.opml';
            a.click();
            URL.revokeObjectURL(url);
        } catch (error) {
            console.error('Failed to export OPML:', error);
        }
    },

    async exportStarred() {
        try {
            let url = `${API_BASE}/posts/export-starred`;
            const params = [];
            if (this.filter === 'feed' && this.filterId) params.push(`feed_id=${this.filterId}`);
            else if (this.filter === 'category' && this.filterId) params.push(`category_id=${this.filterId}`);
            if (params.length) url += '?' + params.join('&');

            const response = await fetch(url, {
                headers: { 'Authorization': `Bearer ${this.token}` },
            });
            if (!response.ok) throw new Error('Export failed');

            const disposition = response.headers.get('Content-Disposition');
            const filename = disposition?.match(/filename="(.+)"/)?.[1] || 'starred.zip';

            const blob = await response.blob();
            const blobUrl = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = blobUrl;
            a.download = filename;
            a.click();
            URL.revokeObjectURL(blobUrl);
        } catch (error) {
            console.error('Failed to export starred posts:', error);
        }
    },

    // --- Tag consolidation (merge + purge) ---
    async previewRareTags() {
        this.purgeLoading = true;
        try {
            const data = await this.fetchApi(`/tags/rare-preview?max_count=${this.purgeMaxCount}`);
            this.purgeBreakdowns = data.breakdowns || [];
            this.purgeTotalTags = data.total_tags;
            this.purgeSample = data.sample || [];
        } catch (e) {
            this.showToast(e.message || this.t('errors.requestFailed'), 'error');
        } finally {
            this.purgeLoading = false;
        }
    },

    async purgeRareTags() {
        const count = this.purgeBreakdowns[this.purgeMaxCount - 1]?.tag_count || 0;
        if (!count) return;
        if (!await this.showConfirm(
            this.t('settings.tagMerge.purgeConfirm')
                .replace('{count}', count)
                .replace('{threshold}', this.purgeMaxCount)
        )) return;

        this.confirmLoading(this.t('settings.tagMerge.purgeStarting'));

        try {
            const headers = { 'Content-Type': 'application/json' };
            if (this.token) headers['Authorization'] = `Bearer ${this.token}`;

            const response = await fetch(`${API_BASE}/tags/purge-rare`, {
                method: 'POST',
                headers,
                body: JSON.stringify({ max_count: this.purgeMaxCount }),
            });

            if (response.status === 401) { this.logout(); return; }
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || this.t('errors.requestFailed'));
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';
            let result = null;

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                while (buffer.includes('\n')) {
                    const nl = buffer.indexOf('\n');
                    const line = buffer.slice(0, nl);
                    buffer = buffer.slice(nl + 1);
                    if (!line.trim()) continue;
                    const event = JSON.parse(line);
                    if (event.type === 'progress') {
                        this.confirmLoading(
                            this.t('settings.tagMerge.purgeProgress')
                                .replace('{deleted}', event.deleted)
                                .replace('{total}', event.total)
                        );
                    } else if (event.type === 'done') {
                        result = event;
                    }
                }
            }

            this.confirmDone();
            if (result) {
                this.showToast(
                    this.t('settings.tagMerge.purgeSuccess')
                        .replace('{tags}', result.tags_removed)
                        .replace('{rows}', result.rows_deleted),
                    'success'
                );
            }
            await this.previewRareTags();
        } catch (e) {
            this.confirmDone();
            this.showToast(e.message || this.t('errors.requestFailed'), 'error');
        }
    },

    async suggestTagMerges() {
        this.mergeSuggesting = true;
        try {
            const data = await this.fetchApi('/tags/suggest-merges', {
                method: 'POST',
                body: JSON.stringify({ offset: this.mergeOffset, batch_size: this.mergeBatchSize }),
            });
            this.mergeTotalTags = data.total_tags;
            this.mergeGroups = (data.groups || []).map(g => ({
                canonical: g.canonical,
                merge: [...g.merge],
                selected: true,
            }));
            if (this.mergeGroups.length === 0) {
                this.mergeOffset += this.mergeBatchSize;
                this.showToast(this.t('settings.tagMerge.noGroups'), 'info');
            }
        } catch (e) {
            this.showToast(e.message || this.t('errors.requestFailed'), 'error');
        } finally {
            this.mergeSuggesting = false;
        }
    },

    async applyTagMerges() {
        const selected = this.mergeGroups.filter(g => g.selected && g.merge.length > 0);
        if (selected.length === 0) return;
        this.mergeApplying = true;
        try {
            const data = await this.fetchApi('/tags/apply-merges', {
                method: 'POST',
                body: JSON.stringify({
                    merges: selected.map(g => ({ canonical: g.canonical, merge: g.merge })),
                }),
            });
            const msg = this.t('settings.tagMerge.success')
                .replace('{merged}', data.tags_merged)
                .replace('{posts}', data.posts_affected);
            this.showToast(msg, 'success');
            this.mergeGroups = this.mergeGroups.filter(g => !g.selected);
            if (this.mergeGroups.length === 0) {
                this.mergeOffset += this.mergeBatchSize;
            }
        } catch (e) {
            this.showToast(e.message || this.t('errors.requestFailed'), 'error');
        } finally {
            this.mergeApplying = false;
            this.$nextTick(() => {
                if (!this.showSettings) {
                    this.showSettings = true;
                    history.pushState({ modal: 'settings' }, '');
                }
            });
        }
    },

    // --- Ignored tags ---
    async loadIgnoredTags() {
        try {
            const data = await this.fetchApi('/tags/ignored');
            this.ignoredTags = new Set(data.tags || []);
        } catch (e) {
            console.warn('Failed to load ignored tags:', e);
        }
    },

    async toggleTagIgnored(tag) {
        const normalized = tag.toLowerCase();
        try {
            if (this.ignoredTags.has(normalized)) {
                await this.fetchApi(`/tags/ignored/${encodeURIComponent(normalized)}`, { method: 'DELETE' });
                this.ignoredTags.delete(normalized);
            } else {
                await this.fetchApi('/tags/ignored', {
                    method: 'POST',
                    body: JSON.stringify({ tag: normalized }),
                });
                this.ignoredTags.add(normalized);
            }
            this.ignoredTags = new Set(this.ignoredTags);
        } catch (e) {
            console.warn('Failed to toggle ignored tag:', e);
        }
    },

    isTagIgnored(tag) {
        return this.ignoredTags.has(tag.toLowerCase());
    },

    // --- Topic management (settings) ---
    async createTopic(name, tags = []) {
        try {
            const result = await this.fetchApi('/topics', {
                method: 'POST',
                body: JSON.stringify({ name, tags }),
            });
            await this.loadTopics();
            return result;
        } catch (e) {
            this.showToast(e.message, 'error');
            return null;
        }
    },

    async deleteTopic(topicId) {
        const topic = this.topics.find(t => t.id === topicId);
        const name = topic ? topic.name : 'this topic';
        if (!await this.showConfirm(this.t('settings.topics.deleteConfirm').replace('{name}', name))) return;

        this.confirmLoading(this.t('confirm.deleting'));
        try {
            await this.fetchApi(`/topics/${topicId}`, { method: 'DELETE' });
            if (this.selectedTopicId === topicId) {
                this.selectedTopicId = null;
            }
            await this.loadTopics();
        } catch (e) {
            this.showToast(e.message, 'error');
        } finally {
            this.confirmDone();
        }
    },

    async renameTopic(topicId) {
        if (this.editingTopic !== topicId) return; // guard against double-fire (blur + enter)
        const name = this.editingTopicName.trim();
        if (!name) {
            this.editingTopic = null;
            return;
        }
        const topic = this.topics.find(t => t.id === topicId);
        if (topic && name === topic.name) {
            this.editingTopic = null;
            return;
        }
        this.editingTopic = null; // exit edit mode immediately
        try {
            await this.fetchApi(`/topics/${topicId}`, {
                method: 'PUT',
                body: JSON.stringify({ name }),
            });
            await this.loadTopics();
        } catch (e) {
            this.showToast(e.message, 'error');
            await this.loadTopics(); // reload to restore correct state
        }
    },

    async addTagsToTopic(topicId, tags) {
        try {
            await this.fetchApi(`/topics/${topicId}/tags`, {
                method: 'POST',
                body: JSON.stringify({ tags }),
            });
            await this.loadTopics();
        } catch (e) {
            this.showToast(e.message, 'error');
        }
    },

    async removeTagFromTopic(topicId, tag) {
        try {
            await this.fetchApi(`/topics/${topicId}/tags/${encodeURIComponent(tag)}`, {
                method: 'DELETE',
            });
            await this.loadTopics();
        } catch (e) {
            this.showToast(e.message, 'error');
        }
    },

    // --- Tag drag-and-drop between topics ---
    // Option/Alt + drag = copy; plain drag = move
    onTagDragStart(event, tag, topicId) {
        this.dragTagName = tag;
        this.dragTagFromTopicId = topicId;
        this.dragTagCopy = false;
        event.dataTransfer.effectAllowed = 'all';
        event.dataTransfer.setData('text/plain', tag);
        event.target.style.opacity = '0.5';
    },

    onTagDragEnd(event) {
        event.target.style.opacity = '';
        setTimeout(() => {
            this.dragTagName = null;
            this.dragTagFromTopicId = null;
            this.dragOverTopicId = null;
            this.dragTagCopy = false;
        }, 0);
    },

    onTopicDragOver(event, topicId) {
        if (this.dragTagName === null) return;
        event.preventDefault();
        this.dragTagCopy = event.altKey;
        this.dragOverTopicId = topicId;
    },

    onTopicDragLeave(event, topicId) {
        if (!event.currentTarget.contains(event.relatedTarget)) {
            if (this.dragOverTopicId === topicId) {
                this.dragOverTopicId = null;
            }
        }
    },

    async onTopicDrop(event, topicId) {
        event.preventDefault();
        const tag = this.dragTagName;
        const fromTopicId = this.dragTagFromTopicId;
        const isCopy = this.dragTagCopy || event.altKey;

        this.dragOverTopicId = null;
        this.dragTagName = null;
        this.dragTagFromTopicId = null;

        if (!tag || !fromTopicId || fromTopicId === topicId) return;

        // Check if target topic already has this tag
        const targetTopic = this.topics.find(t => t.id === topicId);
        if (targetTopic && targetTopic.tags.includes(tag)) return;

        try {
            // Add to target
            await this.fetchApi(`/topics/${topicId}/tags`, {
                method: 'POST',
                body: JSON.stringify({ tags: [tag] }),
            });
            // Remove from source (move only)
            if (!isCopy) {
                await this.fetchApi(`/topics/${fromTopicId}/tags/${encodeURIComponent(tag)}`, {
                    method: 'DELETE',
                });
            }
            await this.loadTopics();
        } catch (e) {
            this.showToast(e.message, 'error');
            await this.loadTopics();
        }
    },

    async suggestTopics() {
        this.suggestingTopics = true;
        this.topicSuggestions = null;
        try {
            const data = await this.fetchApi('/topics/suggest', { method: 'POST' });
            this.topicSuggestions = data;
        } catch (e) {
            this.showToast(e.message, 'error');
        } finally {
            this.suggestingTopics = false;
        }
    },

    async acceptTopicSuggestion(suggestion) {
        const result = await this.createTopic(suggestion.name, suggestion.tags);
        if (result) {
            this.topicSuggestions.suggestions = this.topicSuggestions.suggestions.filter(
                s => s.name !== suggestion.name
            );
            this.showToast(`Topic "${suggestion.name}" created`, 'success');
        }
    },

    async acceptAllTopicSuggestions() {
        if (!this.topicSuggestions?.suggestions?.length) return;
        for (const suggestion of [...this.topicSuggestions.suggestions]) {
            await this.createTopic(suggestion.name, suggestion.tags);
        }
        this.topicSuggestions = null;
        this.showToast('All topics created', 'success');
    },

    async suggestTagsForTopic(topicId) {
        if (this.suggestingTagsForTopicId) return;
        this.suggestingTagsForTopicId = topicId;
        try {
            const data = await this.fetchApi(`/topics/${topicId}/suggest-tags`, { method: 'POST' });
            if (data.tags && data.tags.length > 0) {
                await this.addTagsToTopic(topicId, data.tags);
                const topic = this.topics.find(t => t.id === topicId);
                this.showToast(`${data.tags.length} tags added to "${topic?.name || 'topic'}"`, 'success');
            } else {
                this.showToast('No matching tags found', 'info');
            }
        } catch (e) {
            this.showToast(e.message, 'error');
        } finally {
            this.suggestingTagsForTopicId = null;
        }
    },

    async addTagFilterToTopic(topicId) {
        if (!this.tagFilter) return;
        await this.addTagsToTopic(topicId, [this.tagFilter]);
        this.showToast(`Tag "${this.tagFilter}" added to topic`, 'success');
    },

    // --- AI settings ---
    async loadSummaryLanguages() {
        try {
            const response = await fetch(`${API_BASE}/admin/languages`);
            if (response.ok) {
                this.availableSummaryLanguages = await response.json();
                const saved = this.summaryLanguage;
                this.$nextTick(() => { this.summaryLanguage = saved; });
            }
        } catch (e) {
            console.warn('Failed to load summary languages:', e);
        }
    },

    async loadAvailableModels() {
        try {
            const models = await this.fetchApi('/admin/models');
            this.availableModels = models || [];
            const saved = this.cerebrasModel;
            this.$nextTick(() => { this.cerebrasModel = saved; });
        } catch (e) {
            console.warn('Failed to load AI models:', e);
            this.availableModels = [];
        }
    },

    setSummaryLanguage(language) {
        this.summaryLanguage = language;
        if (this.token) this.savePreferencesToServer();
    },

    setCerebrasModel(model) {
        this.cerebrasModel = model;
        if (this.token) this.savePreferencesToServer();
    },

    async loadPromptDefaults() {
        try {
            const data = await this.fetchApi('/admin/prompt-defaults');
            this.defaultSystemPrompt = data.system_prompt;
            this.defaultUserPrompt = data.user_prompt;
        } catch (e) {
            console.warn('Failed to load prompt defaults:', e);
        }
    },

    resetPromptsToDefaults() {
        this.systemPrompt = this.defaultSystemPrompt;
        this.userPrompt = this.defaultUserPrompt;
    },

    async saveAiSettings() {
        try {
            const payload = {
                system_prompt: this.systemPrompt,
                user_prompt: this.userPrompt,
            };
            if (this.cerebrasApiKeys && !this.cerebrasApiKeys.includes('****')) {
                payload.cerebras_api_keys = this.cerebrasApiKeys;
            }
            await this.fetchApi('/preferences', {
                method: 'PUT',
                body: JSON.stringify(payload),
            });
        } catch (e) {
            console.error('Failed to save AI settings:', e);
            this.showError(e.message);
        }
    },

    // --- Locale / theme setters ---
    async setLocale(locale) {
        await this.loadLocale(locale);
        if (this.token) this.savePreferencesToServer();
    },

    setTheme(theme) {
        this.theme = theme;
        localStorage.setItem('rss_theme', theme);
        this.applyTheme();
        if (this.token) this.savePreferencesToServer();
    },

    // --- Data settings setters ---
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

    // --- Interface settings setters ---
    setToastTimeout(value) {
        this.toastTimeoutSeconds = parseInt(value) || 2;
        if (this.token) this.savePreferencesToServer();
    },

    setIdleRefresh(value) {
        this.idleRefreshSeconds = parseInt(value) || 180;
        this.resetIdleTimer();
        if (this.token) this.savePreferencesToServer();
    },

    setSuggestionMinTags(value) {
        this.suggestionMinTags = Math.max(1, Math.min(this.tagsPerPost, parseInt(value) || 3));
        if (this.token) this.savePreferencesToServer();
    },

    setProfileMinTagFreq(value) {
        this.profileMinTagFreq = Math.max(1, Math.min(20, parseInt(value) || 2));
        if (this.token) this.savePreferencesToServer();
    },

    setTagsPerPost(value) {
        this.tagsPerPost = Math.max(3, Math.min(15, parseInt(value) || 7));
        if (this.token) this.savePreferencesToServer();
    },

    setModelCooldown(value) {
        this.modelCooldownMinutes = Math.max(5, Math.min(120, parseInt(value) || 30));
        if (this.token) this.savePreferencesToServer();
    },

    setBlockedTerms(value) {
        const lines = value.split('\n').map(l => l.trim().toLowerCase()).filter(l => l);
        const unique = [...new Set(lines)].sort();
        this.blockedTerms = unique.join('\n');
        if (this.token) {
            this.savePreferencesToServer();
            // Reload posts so is_blocked is recalculated by backend
            this.loadPosts(true);
        }
    },

    setReadingMode(mode) {
        this.readingMode = mode;
        if (this.currentPost) {
            this.currentPost = null;
        }
        if (this.token) this.savePreferencesToServer();
    },

    // --- Split view resize ---
    startResize(e) {
        e.preventDefault();
        this.resizing = true;
        this._doResize = this.doResize.bind(this);
        this._stopResize = this.stopResize.bind(this);
        document.addEventListener('mousemove', this._doResize);
        document.addEventListener('mouseup', this._stopResize);
        document.addEventListener('touchmove', this._doResize, { passive: false });
        document.addEventListener('touchend', this._stopResize);
        document.addEventListener('touchcancel', this._stopResize);
        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'row-resize';
    },

    doResize(e) {
        e.preventDefault();
        const container = document.getElementById('split-container');
        if (!container) return;
        const rect = container.getBoundingClientRect();
        const clientY = e.touches ? e.touches[0].clientY : e.clientY;
        let ratio = ((clientY - rect.top) / rect.height) * 100;
        this.splitRatio = Math.min(80, Math.max(20, Math.round(ratio)));
    },

    stopResize() {
        this.resizing = false;
        document.removeEventListener('mousemove', this._doResize);
        document.removeEventListener('mouseup', this._stopResize);
        document.removeEventListener('touchmove', this._doResize);
        document.removeEventListener('touchend', this._stopResize);
        document.removeEventListener('touchcancel', this._stopResize);
        document.body.style.userSelect = '';
        document.body.style.cursor = '';
        if (this.token) this.savePreferencesToServer();
    },

    // --- Preferences sync ---
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
                    profile_min_tag_freq: this.profileMinTagFreq,
                    tags_per_post: this.tagsPerPost,
                    model_cooldown_minutes: this.modelCooldownMinutes,
                    blocked_terms: this.blockedTerms,
                }),
            });
        } catch (e) {
            console.warn('Failed to save preferences to server:', e);
        }
    },

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
                await this.savePreferencesToServer();
            }

            // AI settings
            if (serverPrefs.summary_language) this.summaryLanguage = serverPrefs.summary_language;
            if (serverPrefs.cerebras_model) this.cerebrasModel = serverPrefs.cerebras_model;

            // Data settings
            if (serverPrefs.feed_update_interval) this.feedUpdateInterval = serverPrefs.feed_update_interval;
            if (serverPrefs.max_posts_per_feed) this.maxPostsPerFeed = serverPrefs.max_posts_per_feed;
            if (serverPrefs.max_post_age_days) this.maxPostAgeDays = serverPrefs.max_post_age_days;
            if (serverPrefs.max_unread_days) this.maxUnreadDays = serverPrefs.max_unread_days;

            // Interface settings
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
            if (serverPrefs.profile_min_tag_freq !== null && serverPrefs.profile_min_tag_freq !== undefined) {
                this.profileMinTagFreq = serverPrefs.profile_min_tag_freq;
            }
            if (serverPrefs.tags_per_post !== null && serverPrefs.tags_per_post !== undefined) {
                this.tagsPerPost = serverPrefs.tags_per_post;
            }
            if (serverPrefs.model_cooldown_minutes !== null && serverPrefs.model_cooldown_minutes !== undefined) {
                this.modelCooldownMinutes = serverPrefs.model_cooldown_minutes;
            }
            if (serverPrefs.reading_mode) this.readingMode = serverPrefs.reading_mode;
            if (serverPrefs.split_ratio !== null && serverPrefs.split_ratio !== undefined) {
                this.splitRatio = serverPrefs.split_ratio;
            }

            // AI keys and prompts
            if (serverPrefs.cerebras_api_keys) this.cerebrasApiKeys = serverPrefs.cerebras_api_keys;
            if (serverPrefs.system_prompt) this.systemPrompt = serverPrefs.system_prompt;
            if (serverPrefs.user_prompt) this.userPrompt = serverPrefs.user_prompt;
            if (serverPrefs.blocked_terms !== null && serverPrefs.blocked_terms !== undefined) {
                this.blockedTerms = serverPrefs.blocked_terms;
            }
        } catch (e) {
            console.warn('Failed to sync preferences:', e);
        }
    },

    // --- Misc settings actions ---
    async resetCircuitBreaker() {
        try {
            await this.fetchApi('/admin/reset-circuit-breaker', { method: 'POST' });
            this.showToast(this.t('settings.circuitBreakerReset'));
        } catch (error) {
            console.error('Failed to reset circuit breaker:', error);
        }
    },

    clearCacheAndReload() {
        localStorage.clear();
        window.location.href = window.location.pathname + '?_=' + Date.now();
    },
};
