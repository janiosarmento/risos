/**
 * Curation mixin — AI curation, batch operations, export selection
 *
 * Spread into app() via ...curationMixin so `this` is the Alpine component.
 * Dependencies from app: starredCount, selectedTopicId, tagFilter, filter,
 *   filterId, selectMode, selectedPosts, token, fetchApi(), loadPosts(),
 *   showToast(), showConfirm(), confirmLoading(), confirmDone(), t()
 */
const curationMixin = {
    // State
    curationResults: null,
    curationStats: { essential: 0, situational: 0, redundant: 0, unclassified: 0 },
    curatingPosts: false,

    // Run AI curation on starred posts
    async curatePosts() {
        // Warn if too many posts for AI context window
        if (this.starredCount > CURATION_WARN_THRESHOLD) {
            if (!await this.showConfirm(this.t('curation.tooManyPosts').replace('{count}', this.starredCount))) return;
            this.confirmDone();
        }
        this.curatingPosts = true;
        this.curationResults = null;

        this.curationStats = { essential: 0, situational: 0, redundant: 0, unclassified: 0 };
        try {
            const body = {};
            if (this.selectedTopicId) body.topic_id = this.selectedTopicId;
            if (this.tagFilter) body.tag = this.tagFilter;
            if (this.filter === 'feed') body.feed_id = this.filterId;
            else if (this.filter === 'category') body.category_id = this.filterId;
            const data = await this.fetchApi('/posts/curate', {
                method: 'POST',
                body: JSON.stringify(body),
            });
            // Build lookup map: post_id -> { classification, reason }
            const map = {};
            for (const item of (data.analysis?.essential || [])) {
                map[item.post_id] = { classification: 'essential', reason: item.reason || '' };
            }
            for (const item of (data.analysis?.redundant || [])) {
                map[item.post_id] = { classification: 'redundant', reason: item.reason || '', covered_by: item.covered_by };
            }
            for (const item of (data.analysis?.keep_if_interested || [])) {
                map[item.post_id] = { classification: 'keep_if_interested', reason: item.reason || '' };
            }
            // Compute stats from final map (avoids double-counting if AI duplicates a post)
            const stats = { essential: 0, situational: 0, redundant: 0, unclassified: 0, total: data.total_posts || 0 };
            for (const info of Object.values(map)) {
                if (info.classification === 'essential') stats.essential++;
                else if (info.classification === 'redundant') stats.redundant++;
                else stats.situational++;
            }
            const classified = stats.essential + stats.situational + stats.redundant;
            stats.unclassified = Math.max(0, stats.total - classified);
            this.curationResults = map;
            this.curationStats = stats;
        } catch (e) {
            console.error('Curation error:', e);
            this.showToast(e.message || 'Request failed', 'error');
        } finally {
            this.curatingPosts = false;
        }
    },

    // Get curation badge for a post
    getCurationBadge(postId) {
        if (!this.curationResults) return null;
        return this.curationResults[postId] || null;
    },

    // Select all redundant posts
    selectRedundantPosts() {
        if (!this.curationResults) return;
        this.selectMode = true;
        this.selectedPosts = new Set();
        for (const [postId, info] of Object.entries(this.curationResults)) {
            if (info.classification === 'redundant') {
                this.selectedPosts.add(parseInt(postId));
            }
        }
        this.selectedPosts = new Set(this.selectedPosts);
    },

    // Batch unstar selected posts
    async batchUnstar() {
        const ids = [...this.selectedPosts];
        if (!ids.length) return;
        if (!await this.showConfirm(this.t('curation.archiveConfirm'))) return;
        this.confirmLoading(this.t('confirm.deleting'));
        try {
            const data = await this.fetchApi('/posts/batch-unstar', {
                method: 'POST',
                body: JSON.stringify({ post_ids: ids }),
            });
            this.showToast(`${data.count} posts unstarred`, 'success');
            this.selectedPosts = new Set();
            this.selectMode = false;
            this.curationResults = null;
            this.loadPosts(true);
        } catch (e) {
            this.showToast(e.message, 'error');
        } finally {
            this.confirmDone();
        }
    },

    // Export selected posts as ZIP
    async exportSelection() {
        const ids = [...this.selectedPosts];
        if (!ids.length) return;
        try {
            const response = await fetch(`${API_BASE}/posts/export-selection`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${this.token}`,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ post_ids: ids }),
            });
            if (!response.ok) throw new Error('Export failed');
            const disposition = response.headers.get('Content-Disposition');
            const filename = disposition?.match(/filename="(.+)"/)?.[1] || 'selection.zip';
            const blob = await response.blob();
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = filename;
            a.click();
            URL.revokeObjectURL(a.href);
        } catch (e) {
            this.showToast(e.message || 'Export failed', 'error');
        }
    },

    // Clear curation results
    clearCuration() {
        this.curationResults = null;
        this.curationStats = { essential: 0, situational: 0, redundant: 0, unclassified: 0 };
    },
};
