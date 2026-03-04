/**
 * AuthStore — token management and API helper
 */
document.addEventListener('alpine:init', () => {
    Alpine.store('auth', {
        token: sessionStorage.getItem('rss_token'),

        async fetchApi(endpoint, options = {}) {
            const headers = {
                'Content-Type': 'application/json',
                ...options.headers,
            };

            if (this.token) {
                headers['Authorization'] = `Bearer ${this.token}`;
            }

            const response = await fetch(`${API_BASE}${endpoint}`, {
                ...options,
                headers,
            });

            if (response.status === 401) {
                this.token = null;
                sessionStorage.removeItem('rss_token');
                throw new Error('Session expired');
            }

            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(data.detail || 'Request failed');
            }

            if (response.status === 204) {
                return null;
            }

            return response.json();
        }
    });
});
