/**
 * PreferencesStore — all user preference values
 * Methods that depend on other stores (fetchApi, loadLocale, etc.)
 * remain in app.js and access these values via the store.
 */
document.addEventListener('alpine:init', () => {
    Alpine.store('prefs', {
        // AI Settings
        summaryLanguage: null,
        cerebrasModel: null,
        availableSummaryLanguages: [],
        availableModels: [],
        cerebrasApiKeys: '',
        systemPrompt: '',
        userPrompt: '',
        defaultSystemPrompt: '',
        defaultUserPrompt: '',
        tagsPerPost: 7,
        modelCooldownMinutes: 30,

        // Data Settings
        feedUpdateInterval: 30,
        maxPostsPerFeed: 500,
        maxPostAgeDays: 365,
        maxUnreadDays: 90,

        // Interface Settings
        toastTimeoutSeconds: 2,
        idleRefreshSeconds: 180,
        readingMode: 'fullscreen',
        splitRatio: 40,
        suggestionMinTags: 3,
        profileMinTagFreq: 2,
        blockedTerms: '',
    });
});
