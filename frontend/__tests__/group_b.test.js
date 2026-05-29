/**
 * @jest-environment jsdom
 *
 * Group B tests — race condition fix + 401 centralisation.
 *
 * Fix #1 — _creatingConversation serializes concurrent addMessage calls
 * Fix #2 — _fetchWithAuth redirects on 401 for all methods
 */

// ─── Minimal stubs ────────────────────────────────────────────────────────────
global.localStorage = (() => {
    const store = {};
    return {
        getItem: (k) => store[k] ?? null,
        setItem: (k, v) => { store[k] = v; },
        removeItem: (k) => { delete store[k]; },
    };
})();

global.window = global.window || {};
global.API_BASE_URL = 'http://localhost:8002';

global.Auth = {
    getAuthHeaders: () => {
        const t = global.localStorage.getItem('authToken');
        return t ? { Authorization: `Bearer ${t}` } : {};
    },
};

const { ConversationManager } = require('../conversation_manager.js');

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeFetch(responses) {
    // responses: array of { status, body } returned in order
    let i = 0;
    return jest.fn(() => {
        const r = responses[i++] || { status: 200, body: {} };
        return Promise.resolve({
            ok: r.status >= 200 && r.status < 300,
            status: r.status,
            json: () => Promise.resolve(r.body),
        });
    });
}

function makeManager() {
    // Prevent auto-init from firing real network
    const m = Object.create(ConversationManager.prototype);
    m.apiBaseUrl = 'http://localhost:8002';
    m.currentConversationId = null;
    m.conversations = [];
    m.currentMessages = [];
    m.pageSize = 100;
    m.totalCount = 0;
    m.isLoading = false;
    m._persistenceQueue = [];
    m._retryScheduled = false;
    m._creatingConversation = null;
    m.listeners = {};
    return m;
}

// ─── Fix #1 — Race condition: _creatingConversation serialization ─────────────

describe('Fix #1 — addMessage race condition', () => {
    test('two concurrent addMessage calls share one createConversation promise', async () => {
        const manager = makeManager();

        let resolveCreate;
        const createProm = new Promise((res) => { resolveCreate = res; });

        manager.createConversation = jest.fn(() => {
            manager.currentConversationId = 'conv-1';
            return createProm;
        });

        const msgResponse = { id: 'msg-1', role: 'user', content: 'hello', created_at: new Date().toISOString() };
        global.fetch = makeFetch([
            { status: 200, body: msgResponse },
            { status: 200, body: { ...msgResponse, id: 'msg-2', content: 'world' } },
        ]);

        // Fire both addMessage before createConversation resolves
        const p1 = manager.addMessage('user', 'hello');
        const p2 = manager.addMessage('user', 'world');

        // createConversation should only have been called once
        expect(manager.createConversation).toHaveBeenCalledTimes(1);

        // Resolve the creation
        resolveCreate({ id: 'conv-1', title: null });

        await Promise.all([p1, p2]);

        // Still only one creation
        expect(manager.createConversation).toHaveBeenCalledTimes(1);
    });

    test('_creatingConversation is cleared after creation resolves', async () => {
        const manager = makeManager();
        manager.createConversation = jest.fn(async () => {
            manager.currentConversationId = 'conv-2';
        });
        const msgBody = { id: 'msg-1', role: 'user', content: 'hi', created_at: new Date().toISOString() };
        global.fetch = makeFetch([{ status: 200, body: msgBody }]);

        await manager.addMessage('user', 'hi');
        expect(manager._creatingConversation).toBeNull();
    });

    test('if currentConversationId already set, createConversation is not called', async () => {
        const manager = makeManager();
        manager.currentConversationId = 'existing-conv';
        manager.createConversation = jest.fn();
        const msgBody = { id: 'msg-1', role: 'user', content: 'hi', created_at: new Date().toISOString() };
        global.fetch = makeFetch([{ status: 200, body: msgBody }]);

        await manager.addMessage('user', 'hi');
        expect(manager.createConversation).not.toHaveBeenCalled();
    });
});

// ─── Fix #2 — 401 handling redirects via _fetchWithAuth ──────────────────────

describe('Fix #2 — 401 redirect on all methods', () => {
    let redirectCalled;

    beforeEach(() => {
        redirectCalled = false;
        // Stub redirectToLogin as a global
        global.redirectToLogin = () => { redirectCalled = true; };
    });

    afterEach(() => {
        delete global.redirectToLogin;
    });

    async function assert401(methodFn) {
        global.fetch = makeFetch([{ status: 401, body: {} }]);
        await expect(methodFn()).rejects.toThrow('Session expirée');
        expect(redirectCalled).toBe(true);
    }

    test('loadConversations redirects on 401', async () => {
        const manager = makeManager();
        await assert401(() => manager.loadConversations());
    });

    test('createConversation redirects on 401', async () => {
        const manager = makeManager();
        await assert401(() => manager.createConversation());
    });

    test('loadConversation redirects on 401', async () => {
        const manager = makeManager();
        await assert401(() => manager.loadConversation('conv-1'));
    });

    test('addMessage redirects on 401 (conversation pre-existing)', async () => {
        const manager = makeManager();
        manager.currentConversationId = 'conv-1';
        await assert401(() => manager.addMessage('user', 'hi'));
    });

    test('deleteConversation redirects on 401', async () => {
        const manager = makeManager();
        await assert401(() => manager.deleteConversation('conv-1'));
    });

    test('updateConversation redirects on 401', async () => {
        const manager = makeManager();
        await assert401(() => manager.updateConversation('conv-1', { title: 'x' }));
    });

    test('toggleFavorite redirects on 401', async () => {
        const manager = makeManager();
        await assert401(() => manager.toggleFavorite('conv-1'));
    });

    test('createShareLink redirects on 401', async () => {
        const manager = makeManager();
        await assert401(() => manager.createShareLink('conv-1'));
    });
});

// ─── _fetchWithAuth: auth token forwarded ────────────────────────────────────

describe('_fetchWithAuth: Authorization header', () => {
    test('token from localStorage is included in request headers', async () => {
        localStorage.setItem('authToken', 'tok-abc');
        const manager = makeManager();

        let capturedHeaders;
        global.fetch = jest.fn((url, opts) => {
            capturedHeaders = opts.headers;
            return Promise.resolve({
                ok: true, status: 200,
                json: () => Promise.resolve({ data: [], count: 0 }),
            });
        });

        await manager.loadConversations();
        expect(capturedHeaders['Authorization']).toBe('Bearer tok-abc');
        localStorage.removeItem('authToken');
    });

    test('no Authorization header when no token', async () => {
        localStorage.removeItem('authToken');
        const manager = makeManager();

        let capturedHeaders;
        global.fetch = jest.fn((url, opts) => {
            capturedHeaders = opts.headers;
            return Promise.resolve({
                ok: true, status: 200,
                json: () => Promise.resolve({ data: [], count: 0 }),
            });
        });

        await manager.loadConversations();
        expect(capturedHeaders['Authorization']).toBeUndefined();
    });
});
