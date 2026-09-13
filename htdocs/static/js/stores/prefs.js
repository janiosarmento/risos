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
        // Found/not-found state for the Jano secret name fields (null = not checked yet).
        janoSecretValid: null,
        apiBaseUrl: 'https://api.cerebras.ai/v1',
        // Background AI engine (batch processing)
        backgroundAiModel: null,
        backgroundAvailableModels: [],
        backgroundJanoSecretName: '',
        backgroundJanoSecretValid: null,
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
        curationEngine: 'ondemand',

        // Data Settings
        feedUpdateInterval: 30,
        maxPostAgeDays: 365,
        maxUnreadDays: 90,

        // Interface Settings
        toastTimeoutSeconds: 2,
        idleRefreshSeconds: 180,
        feedReverseOrder: false,
        suggestionMinTags: 3,
        profileMinTagFreq: 2,
        suggestionMinSummaryLength: 100,
        blockedTerms: '',
    });
});
