/**
 * I18nStore — locale, translations, t(), loadLocale()
 */
document.addEventListener('alpine:init', () => {
    Alpine.store('i18n', {
        locale: localStorage.getItem('rss_locale') || null,
        translations: {},
        availableLocales: [],
        ready: false,

        async loadAvailableLocales() {
            try {
                const response = await fetch(`${API_BASE}/admin/locales`);
                if (response.ok) {
                    this.availableLocales = await response.json();
                }
            } catch (e) {
                console.warn('Failed to load available locales:', e);
                this.availableLocales = [
                    { code: 'en-US', name: 'English (US)' },
                    { code: 'pt-BR', name: 'Português (Brasil)' }
                ];
            }
        },

        detectBrowserLocale() {
            const browserLang = navigator.language || navigator.userLanguage || 'en-US';
            const exact = this.availableLocales.find(l => l.code === browserLang);
            if (exact) return exact.code;
            const lang = browserLang.split('-')[0];
            const partial = this.availableLocales.find(l => l.code.startsWith(lang));
            if (partial) return partial.code;
            return this.availableLocales[0]?.code || 'en-US';
        },

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
            } finally {
                this.ready = true;
                const el = document.getElementById('i18n-loading');
                if (el) el.remove();
            }
        }
    });
});
