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
        aiTimeout: 30,
        aiMaxTokens: 8192,
        summaryTemperature: 0.3,
        summaryPresencePenalty: 0.0,

        // Data Settings
        feedUpdateInterval: 30,
        maxPostAgeDays: 365,
        maxUnreadDays: 90,

        // Interface Settings
        toastTimeoutSeconds: 2,
        idleRefreshSeconds: 180,
        readingMode: 'fullscreen',
        splitRatio: 40,
        feedReverseOrder: false,
        suggestionMinTags: 3,
        profileMinTagFreq: 2,
        suggestionMinSummaryLength: 100,
        blockedTerms: '',
    });
});
