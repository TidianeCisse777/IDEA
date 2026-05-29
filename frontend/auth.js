// auth.js — centralise la gestion du token JWT pour tous les modules frontend

const Auth = (function () {
    const api = {};

    api.getToken = function () {
        return localStorage.getItem('authToken');
    };

    api.getAuthHeaders = function () {
        const token = api.getToken();
        return token ? { 'Authorization': `Bearer ${token}` } : {};
    };

    api.isAuthenticated = function () {
        return !!api.getToken();
    };

    api.redirectToLogin = function () {
        window.location.href = 'login.html';
    };

    api.clearToken = function () {
        localStorage.removeItem('authToken');
    };

    api.logout = function () {
        api.clearToken();
        api.redirectToLogin();
    };

    api.checkAuthentication = async function () {
        if (!api.getToken()) {
            api.redirectToLogin();
            return false;
        }
        try {
            const response = await fetch(config.getEndpoints().verify, {
                headers: api.getAuthHeaders(),
            });
            if (response.status === 401) {
                api.clearToken();
                api.redirectToLogin();
                return false;
            }
            // Non-401 errors (5xx, network glitch during restart) — keep token, stay on page
            return response.ok;
        } catch {
            // Network error (container restarting) — do NOT clear token or redirect
            return true;
        }
    };

    return api;
})();

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { Auth };
}
