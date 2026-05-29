/**
 * @jest-environment jsdom
 *
 * Auth module — JWT token management, headers, login redirect.
 */

global.config = {
    getEndpoints: () => ({ verify: '/api/auth/verify' }),
};

const { Auth } = require('../auth.js');

function setToken(t) { window.localStorage.setItem('authToken', t); }
function getToken() { return window.localStorage.getItem('authToken'); }

let redirectSpy;

beforeEach(() => {
    window.localStorage.clear();
    delete global.fetch;
    redirectSpy = jest.spyOn(Auth, 'redirectToLogin').mockImplementation(() => {});
});

afterEach(() => {
    redirectSpy.mockRestore();
});

describe('Auth.getAuthHeaders', () => {
    test('returns empty object when no token in localStorage', () => {
        expect(Auth.getAuthHeaders()).toEqual({});
    });

    test('returns Bearer header when token exists', () => {
        setToken('abc-123');
        expect(Auth.getAuthHeaders()).toEqual({ Authorization: 'Bearer abc-123' });
    });
});

describe('Auth.isAuthenticated', () => {
    test('returns false when no token', () => {
        expect(Auth.isAuthenticated()).toBe(false);
    });

    test('returns true when token present', () => {
        setToken('xyz');
        expect(Auth.isAuthenticated()).toBe(true);
    });
});

describe('Auth.clearToken', () => {
    test('removes authToken from localStorage', () => {
        setToken('will-be-cleared');
        Auth.clearToken();
        expect(getToken()).toBeNull();
    });
});

describe('Auth.logout', () => {
    test('clears token and redirects to login', () => {
        setToken('session-token');
        Auth.logout();
        expect(getToken()).toBeNull();
        expect(redirectSpy).toHaveBeenCalledTimes(1);
    });
});

describe('Auth.checkAuthentication', () => {
    test('no token → redirects and returns false', async () => {
        const result = await Auth.checkAuthentication();
        expect(result).toBe(false);
        expect(redirectSpy).toHaveBeenCalledTimes(1);
    });

    test('valid token + 200 → returns true, no redirect', async () => {
        setToken('valid');
        global.fetch = jest.fn(() => Promise.resolve({ ok: true, status: 200 }));
        const result = await Auth.checkAuthentication();
        expect(result).toBe(true);
        expect(redirectSpy).not.toHaveBeenCalled();
    });

    test('token + 401 → clears token and redirects', async () => {
        setToken('expired');
        global.fetch = jest.fn(() => Promise.resolve({ ok: false, status: 401 }));
        const result = await Auth.checkAuthentication();
        expect(result).toBe(false);
        expect(getToken()).toBeNull();
        expect(redirectSpy).toHaveBeenCalledTimes(1);
    });

    test('network error → keeps token, stays on page, returns true', async () => {
        setToken('keep-me');
        global.fetch = jest.fn(() => Promise.reject(new Error('network down')));
        const result = await Auth.checkAuthentication();
        expect(result).toBe(true);
        expect(getToken()).toBe('keep-me');
        expect(redirectSpy).not.toHaveBeenCalled();
    });
});
