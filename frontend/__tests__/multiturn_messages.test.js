/**
 * @jest-environment jsdom
 *
 * Multi-turn conversation message flow tests.
 *
 * Verifies that ConversationManager correctly handles the user→LLM→user→LLM
 * message sequence so that each new user message is correctly appended after
 * the assistant's response and the next request carries it as messages[-1].
 */

global.window = global.window || {};
global.window.API_BASE_URL = 'http://localhost:8002';
global.API_BASE_URL = 'http://localhost:8002';

const _storage = {};
global.localStorage = {
    getItem: (k) => _storage[k] ?? null,
    setItem: (k, v) => { _storage[k] = v; },
    removeItem: (k) => { delete _storage[k]; },
};

global.Auth = {
    getAuthHeaders: () => {
        const t = global.localStorage.getItem('authToken');
        return t ? { Authorization: `Bearer ${t}` } : {};
    },
};

const { ConversationManager, MESSAGE_TYPES, MESSAGE_ROLES } = require('../conversation_manager.js');

// ── helpers ──────────────────────────────────────────────────────────────────

function makeFetch(responses) {
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
    const m = Object.create(ConversationManager.prototype);
    m.apiBaseUrl = 'http://localhost:8002';
    m.currentConversationId = 'conv-1';
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

function msg(id, role, content) {
    return { id, role, content, created_at: new Date().toISOString() };
}

// ── Behavior: user → assistant → user sequence ───────────────────────────────

describe('Multi-turn message accumulation', () => {
    test('user message followed by assistant message, then second user message', async () => {
        const manager = makeManager();
        global.fetch = makeFetch([
            { status: 200, body: msg('m1', 'user', 'Bonjour') },
            { status: 200, body: msg('m2', 'assistant', 'Bonjour ! Comment puis-je aider ?') },
            { status: 200, body: msg('m3', 'user', 'Montre-moi les données') },
        ]);

        await manager.addMessage('user', 'Bonjour');
        await manager.addMessage('assistant', 'Bonjour ! Comment puis-je aider ?');
        await manager.addMessage('user', 'Montre-moi les données');

        expect(global.fetch).toHaveBeenCalledTimes(3);
    });

    test('currentMessages includes messages in order across turns', async () => {
        const manager = makeManager();
        global.fetch = makeFetch([
            { status: 200, body: msg('m1', 'user', 'Turn 1') },
            { status: 200, body: msg('m2', 'assistant', 'Reply 1') },
            { status: 200, body: msg('m3', 'user', 'Turn 2') },
        ]);

        await manager.addMessage('user', 'Turn 1');
        await manager.addMessage('assistant', 'Reply 1');
        await manager.addMessage('user', 'Turn 2');

        // All three messages are in currentMessages
        expect(manager.currentMessages).toHaveLength(3);
        expect(manager.currentMessages[0].role).toBe('user');
        expect(manager.currentMessages[1].role).toBe('assistant');
        expect(manager.currentMessages[2].role).toBe('user');
    });

    test('second user message is last in currentMessages — becomes messages[-1] for next LLM call', async () => {
        const manager = makeManager();
        global.fetch = makeFetch([
            { status: 200, body: msg('m1', 'user', 'first') },
            { status: 200, body: msg('m2', 'assistant', 'response') },
            { status: 200, body: msg('m3', 'user', 'second') },
        ]);

        await manager.addMessage('user', 'first');
        await manager.addMessage('assistant', 'response');
        await manager.addMessage('user', 'second');

        const last = manager.currentMessages[manager.currentMessages.length - 1];
        expect(last.role).toBe('user');
        expect(last.content).toBe('second');
    });
});

// ── Behavior: conversation ID is stable across turns ─────────────────────────

describe('Conversation ID stability across turns', () => {
    test('currentConversationId does not change between turns', async () => {
        const manager = makeManager();
        const initialId = manager.currentConversationId;

        global.fetch = makeFetch([
            { status: 200, body: msg('m1', 'user', 'Turn 1') },
            { status: 200, body: msg('m2', 'assistant', 'Reply') },
            { status: 200, body: msg('m3', 'user', 'Turn 2') },
        ]);

        await manager.addMessage('user', 'Turn 1');
        expect(manager.currentConversationId).toBe(initialId);

        await manager.addMessage('assistant', 'Reply');
        expect(manager.currentConversationId).toBe(initialId);

        await manager.addMessage('user', 'Turn 2');
        expect(manager.currentConversationId).toBe(initialId);
    });
});

// ── Behavior: message persistence endpoint receives correct conversation ID ───

describe('Persistence — correct conversation ID in POST body', () => {
    test('each addMessage call posts to the correct conversation endpoint', async () => {
        const manager = makeManager();
        global.fetch = makeFetch([
            { status: 200, body: msg('m1', 'user', 'hello') },
            { status: 200, body: msg('m2', 'assistant', 'hi') },
        ]);

        await manager.addMessage('user', 'hello');
        await manager.addMessage('assistant', 'hi');

        const urls = global.fetch.mock.calls.map(([url]) => url);
        urls.forEach(url => {
            expect(String(url)).toContain('/conversations/conv-1/messages');
        });
    });
});
