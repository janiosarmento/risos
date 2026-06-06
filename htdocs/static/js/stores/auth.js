/**
 * AuthStore — session management and API helper
 * Uses httpOnly session cookie (no token management needed).
 */
document.addEventListener('alpine:init', () => {
    Alpine.store('auth', {
        authenticated: false,  // Tracks login state (cookie-based, no token)

        async fetchApi(endpoint, options = {}) {
            const headers = {
                'Content-Type': 'application/json',
                ...options.headers,
            };

            const response = await fetch(`${API_BASE}${endpoint}`, {
                ...options,
                headers,
            });

            if (response.status === 401) {
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
