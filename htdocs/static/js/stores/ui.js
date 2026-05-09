/**
 * UIStore — toast, confirmModal, theme, applyTheme
 */
document.addEventListener('alpine:init', () => {
    Alpine.store('ui', {
        // Toast
        toast: {
            show: false,
            message: '',
            type: 'info',
            timeoutId: null,
        },

        showToast(message, type = 'info', autoClose = true, timeoutSeconds = 2) {
            if (this.toast.timeoutId) {
                clearTimeout(this.toast.timeoutId);
            }
            this.toast.message = message;
            this.toast.type = type;
            this.toast.show = true;

            const duration = type === 'error'
                ? Math.max(timeoutSeconds * 3, 10) * 1000
                : timeoutSeconds * 1000;

            if (autoClose && timeoutSeconds > 0) {
                this.toast.timeoutId = setTimeout(() => {
                    this.hideToast();
                }, duration);
            }
        },

        hideToast() {
            this.toast.show = false;
        },

        // Confirm modal
        confirmModal: {
            show: false,
            message: '',
            resolve: null,
            loading: false,
        },

        showConfirm(message) {
            return new Promise((resolve) => {
                this.confirmModal.message = message;
                this.confirmModal.resolve = resolve;
                this.confirmModal.show = true;
                setTimeout(() => {
                    const btn = document.getElementById('confirm-ok-btn');
                    if (btn) btn.focus();
                }, 50);
            });
        },

        confirmOk() {
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

        // Font scale
        fontScale: parseInt(sessionStorage.getItem('rss_font_scale') ?? '2', 10),
        fontScales: [0.88, 0.94, 1.00, 1.12, 1.25],

        applyFontScale() {
            const scale = this.fontScales[this.fontScale];
            document.documentElement.style.fontSize = (scale * 100) + '%';
        },

        increaseFontScale() {
            if (this.fontScale < this.fontScales.length - 1) {
                this.fontScale++;
                sessionStorage.setItem('rss_font_scale', this.fontScale);
                this.applyFontScale();
            }
        },

        decreaseFontScale() {
            if (this.fontScale > 0) {
                this.fontScale--;
                sessionStorage.setItem('rss_font_scale', this.fontScale);
                this.applyFontScale();
            }
        },

        resetFontScale() {
            this.fontScale = 2;
            sessionStorage.removeItem('rss_font_scale');
            document.documentElement.style.fontSize = '';
        },

        // Theme
        theme: localStorage.getItem('rss_theme') || 'system',
        availableThemes: [
            { value: 'system', labelKey: 'settings.themeSystem' },
            { value: 'light', labelKey: 'settings.themeLight' },
            { value: 'dark', labelKey: 'settings.themeDark' }
        ],

        applyTheme() {
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
            const shouldBeDark = this.theme === 'dark' || (this.theme === 'system' && prefersDark);
            if (shouldBeDark) {
                document.documentElement.classList.add('dark');
            } else {
                document.documentElement.classList.remove('dark');
            }
        }
    });
});
