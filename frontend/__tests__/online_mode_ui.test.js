/**
 * @jest-environment jsdom
 */

function buildDOM() {
    document.body.innerHTML = `
        <button id="accountSettingsButton"></button>
        <button id="accountSettingsButtonMobile"></button>
        <div id="accountSettingsModal" style="display:none"></div>
        <button id="closeAccountSettingsModal"></button>
        <button id="cancelAccountSettingsBtn"></button>
        <form id="accountSettingsForm"></form>
        <input id="currentPasswordInput" />
        <input id="newPasswordInput" />
        <input id="confirmPasswordInput" />
        <input id="userEmailDisplay" />
        <div id="accountSettingsMessage"></div>

        <div id="sessionModeBadge" class="session-mode-badge session-mode-plan" style="display:none">
            <span id="sessionModeLabel">Mode Plan</span>
        </div>
        <button
            id="onlineModeBadge"
            type="button"
            class="session-mode-badge session-mode-online"
            aria-pressed="false"
        >
            <span class="session-mode-icon">cloud_off</span>
            <span class="session-mode-badge-text">
                <span class="session-mode-badge-title">Mode En Ligne</span>
                <span id="onlineModeLabel" class="session-mode-badge-state">OFF</span>
            </span>
        </button>

        <div id="onlineModeSection">
            <input type="checkbox" id="onlineModeToggle" />
            <div id="onlineModeAllowedSources"></div>
        </div>
    `;
}

function flush() {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

describe('Online Mode UI', () => {
    beforeEach(() => {
        jest.resetModules();
        buildDOM();
        global.sessionId = 'session-123';
        global.config = {
            getEndpoints: () => ({
                userProfile: '/api/users/me',
                onlineMode: '/api/session/online-mode',
            }),
        };
        global.localStorage = {
            getItem: jest.fn(() => 'token-abc'),
            setItem: jest.fn(),
            removeItem: jest.fn(),
        };
        global.Auth = {
            getAuthHeaders: () => ({ Authorization: 'Bearer token-abc' }),
        };
        global.ModalUtils = {
            open: (el) => { if (el) el.style.display = 'block'; },
            close: (el) => { if (el) el.style.display = 'none'; },
            bindDismiss: () => {},
        };
        global.fetch = jest.fn((url, opts = {}) => {
            if (String(url).includes('/api/users/me')) {
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({ email: 'user@example.com' }),
                });
            }
            if (String(url).includes('/api/session/online-mode') && (!opts.method || opts.method === 'GET')) {
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({
                        enabled: false,
                        allowed_sources: ['ogsl', 'bio_oracle'],
                    }),
                });
            }
            if (String(url).includes('/api/session/online-mode') && opts.method === 'PUT') {
                return Promise.resolve({
                    ok: true,
                    json: () => Promise.resolve({
                        enabled: true,
                        allowed_sources: ['ogsl', 'bio_oracle'],
                    }),
                });
            }
            return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
        });
        require('../account-settings.js');
        document.dispatchEvent(new Event('DOMContentLoaded'));
    });

    test('renders online mode state and allowlist in account settings', async () => {
        document.getElementById('accountSettingsButton').click();
        await flush();

        expect(document.getElementById('onlineModeToggle').checked).toBe(false);
        expect(document.getElementById('onlineModeLabel').textContent).toContain('OFF');
        expect(document.getElementById('onlineModeAllowedSources').textContent).toContain('ogsl');
        expect(document.getElementById('onlineModeAllowedSources').textContent).toContain('bio_oracle');
    });

    test('toggle persists via backend and updates header badge', async () => {
        document.getElementById('accountSettingsButton').click();
        await flush();

        const toggle = document.getElementById('onlineModeToggle');
        toggle.checked = true;
        toggle.dispatchEvent(new Event('change', { bubbles: true }));
        await flush();

        expect(global.fetch).toHaveBeenCalledWith(
            '/api/session/online-mode',
            expect.objectContaining({
                method: 'PUT',
            })
        );
        expect(document.getElementById('onlineModeLabel').textContent).toBe('ON');
        expect(document.getElementById('onlineModeBadge').getAttribute('aria-pressed')).toBe('true');
    });

    test('clicking the header badge toggles online mode through the same backend', async () => {
        document.getElementById('accountSettingsButton').click();
        await flush();

        const badge = document.getElementById('onlineModeBadge');
        badge.click();
        await flush();

        expect(global.fetch).toHaveBeenCalledWith(
            '/api/session/online-mode',
            expect.objectContaining({
                method: 'PUT',
            })
        );
        expect(document.getElementById('onlineModeLabel').textContent).toBe('ON');
        expect(document.getElementById('onlineModeBadge').getAttribute('aria-pressed')).toBe('true');
    });
});

// ─── Session ID consistency ───────────────────────────────────────────────────
// The X-Session-Id in online-mode requests must match localStorage.getItem('sessionId')
// so the backend reads/writes online mode for the same session used by chat requests.

describe('Online Mode — session ID consistency', () => {
    const SESSION_ID = 'my-session-42';
    const TOKEN = 'token-xyz';

    beforeEach(() => {
        jest.resetModules();
        buildDOM();
        // Use real jsdom localStorage — global.localStorage = {} does not replace
        // the built-in Storage object that account-settings.js reads.
        window.localStorage.setItem('sessionId', SESSION_ID);
        window.localStorage.setItem('authToken', TOKEN);
        global.Auth = {
            getAuthHeaders: () => {
                const t = window.localStorage.getItem('authToken');
                return t ? { Authorization: `Bearer ${t}` } : {};
            },
        };
        global.ModalUtils = {
            open: (el) => { if (el) el.style.display = 'block'; },
            close: (el) => { if (el) el.style.display = 'none'; },
            bindDismiss: () => {},
        };
        global.config = {
            getEndpoints: () => ({
                userProfile: '/api/users/me',
                onlineMode: '/api/session/online-mode',
            }),
        };
        global.fetch = jest.fn(() =>
            Promise.resolve({
                ok: true,
                json: () => Promise.resolve({ enabled: false, allowed_sources: ['ogsl', 'bio_oracle'] }),
            })
        );
        require('../account-settings.js');
        document.dispatchEvent(new Event('DOMContentLoaded'));
    });

    afterEach(() => {
        window.localStorage.clear();
    });

    test('GET online-mode uses sessionId from localStorage as X-Session-Id', async () => {
        document.getElementById('accountSettingsButton').click();
        await flush();

        const getCall = global.fetch.mock.calls.find(([url, opts = {}]) =>
            String(url).includes('/api/session/online-mode') && (!opts.method || opts.method === 'GET')
        );
        expect(getCall).toBeDefined();
        expect(getCall[1].headers['X-Session-Id']).toBe(SESSION_ID);
    });

    test('PUT online-mode uses same sessionId as GET — no divergence mid-toggle', async () => {
        document.getElementById('accountSettingsButton').click();
        await flush();

        // Simulate toggle ON
        global.fetch.mockResolvedValueOnce({
            ok: true,
            json: () => Promise.resolve({ enabled: true, allowed_sources: ['ogsl', 'bio_oracle'] }),
        });
        const toggle = document.getElementById('onlineModeToggle');
        toggle.checked = true;
        toggle.dispatchEvent(new Event('change', { bubbles: true }));
        await flush();

        const putCall = global.fetch.mock.calls.find(([url, opts = {}]) =>
            String(url).includes('/api/session/online-mode') && opts.method === 'PUT'
        );
        expect(putCall).toBeDefined();
        expect(putCall[1].headers['X-Session-Id']).toBe(SESSION_ID);
        // GET and PUT must use the same session ID
        const getCall = global.fetch.mock.calls.find(([url, opts = {}]) =>
            String(url).includes('/api/session/online-mode') && (!opts.method || opts.method === 'GET')
        );
        expect(putCall[1].headers['X-Session-Id']).toBe(getCall[1].headers['X-Session-Id']);
    });
});
