/**
 * AuthStore — session management and API helper
 * Uses httpOnly session cookie (no token management needed).
 */
document.addEventListener('alpine:init', () => {
    Alpine.store('auth', {
        authenticated: false,  // Tracks login state (cookie-based, no token)

        async fetchApi(endpoint, options = {}) {
            // The i18n store may not exist yet on the very first call.
            const t = (key, fallback) =>
                Alpine.store('i18n')?.t(key, fallback) ?? fallback ?? key;
            const headers = {
                'Content-Type': 'application/json',
                ...options.headers,
            };

            const method = (options.method || 'GET').toUpperCase();
            // Retry transient failures once. The backend runs a single (or few)
            // gunicorn workers, so a deploy/restart leaves a ~2-5s window where
            // requests get a network error or 502/503/504. Only retry requests
            // that are safe to repeat: idempotent HTTP methods plus the
            // effectively-idempotent bulk read/unread endpoints.
            const retryable =
                method === 'GET' ||
                method === 'HEAD' ||
                method === 'PUT' ||
                method === 'PATCH' ||
                method === 'DELETE' ||
                /\/(mark-read|mark-unread)$/.test(endpoint);
            const maxAttempts = retryable ? 2 : 1;
            const RETRY_DELAY_MS = 400;
            const sleep = ms => new Promise(r => setTimeout(r, ms));

            let lastError;
            for (let attempt = 1; attempt <= maxAttempts; attempt++) {
                try {
                    const response = await fetch(`${API_BASE}${endpoint}`, {
                        ...options,
                        headers,
                    });

                    if (response.status === 401) {
                        throw new Error('Session expired');
                    }

                    if (!response.ok) {
                        const transient =
                            response.status === 502 ||
                            response.status === 503 ||
                            response.status === 504;
                        if (transient && attempt < maxAttempts) {
                            await sleep(RETRY_DELAY_MS);
                            continue;
                        }
                        const data = await response.json().catch(() => ({}));
                        // A bare "Request failed" is useless when something
                        // goes wrong. The backend usually sends a `detail`,
                        // but a gateway error (worker restarting, upstream
                        // timeout) never does — nginx answers with HTML — so
                        // fall back to naming the status itself.
                        let detail = data.detail;
                        if (Array.isArray(detail)) {
                            // FastAPI validation errors arrive as a list.
                            detail = detail.map(d => d?.msg).filter(Boolean).join('; ');
                        }
                        if (typeof detail !== 'string' || !detail) {
                            detail = transient
                                ? `${t('errors.gatewayError')} (${response.status})`
                                : `${t('errors.requestFailed')} (${response.status}${response.statusText ? ' ' + response.statusText : ''})`;
                        }
                        throw new Error(detail);
                    }

                    if (response.status === 204) {
                        return null;
                    }

                    return response.json();
                } catch (error) {
                    // Network-level failure (fetch itself rejected) — retry if
                    // the request is safe to repeat. Never retry a 401.
                    const isNetworkError =
                        error instanceof TypeError ||
                        error.name === 'AbortError';
                    if (
                        isNetworkError &&
                        attempt < maxAttempts &&
                        error.message !== 'Session expired'
                    ) {
                        lastError = error;
                        await sleep(RETRY_DELAY_MS);
                        continue;
                    }
                    // "Failed to fetch" tells the user nothing and differs per
                    // browser; say what it actually means.
                    if (isNetworkError) {
                        throw new Error(t('errors.serverUnreachable'));
                    }
                    throw error;
                }
            }

            throw lastError instanceof TypeError
                ? new Error(t('errors.serverUnreachable'))
                : (lastError || new Error(t('errors.requestFailed')));
        }
    });
});
