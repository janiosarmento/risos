/**
 * PreferencesStore — all user preference values
 * Methods that depend on other stores (fetchApi, loadLocale, etc.)
 * remain in app.js and access these values via the store.
 */
document.addEventListener('alpine:init', () => {
    Alpine.store('prefs', {
        // AI Settings
        summaryLanguage: null,
        aiModel: null,
        availableSummaryLanguages: [],
        availableModels: [],
        janoSecretName: '',
        apiBaseUrl: 'https://api.cerebras.ai/v1',
        // Background AI engine (batch processing)
        backgroundAiModel: null,
        backgroundAvailableModels: [],
        backgroundJanoSecretName: '',
        backgroundApiBaseUrl: 'https://api.cerebras.ai/v1',
        systemPrompt: '',
        userPrompt: '',
        defaultSystemPrompt: '',
        defaultUserPrompt: '',
        tagsPerPost: 7,
        modelCooldownMinutes: 30,
        aiTimeout: 30,
        aiMaxTokens: 8192,

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
