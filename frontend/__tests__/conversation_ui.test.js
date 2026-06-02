/**
 * @jest-environment jsdom
 *
 * DOM tests for conversation_ui.js — Fix 3 (loadConversation atomic) and
 * Fix 5 (displayConversations reconciliation).
 */

// ─── DOM scaffold ────────────────────────────────────────────────────────────

function buildDOM() {
    document.body.innerHTML = `
        <div id="conversationsModal" style="display:none"></div>
        <button id="conversationsButton"></button>
        <button id="conversationsButtonMobile"></button>
        <button id="closeConversationsModal"></button>
        <input id="conversationSearch" value="" />
        <button id="showAllConversations" class="active"></button>
        <button id="showFavoriteConversations"></button>
        <button id="refreshConversations"></button>
        <button id="loadMoreConversations"></button>
        <span id="conversationCount"></span>
        <div id="conversationsList"></div>
        <aside id="conversationCsvSidebar" class="conversation-csv-sidebar" aria-hidden="true">
            <button id="conversationCsvToggle"></button>
            <div id="conversationCsvList"></div>
            <div id="conversationCsvViewer"></div>
        </aside>
        <div id="chatDisplay"></div>
    `;
}

// ─── Mock factories ──────────────────────────────────────────────────────────

function makeConversationManager(conversations = [], currentId = null, messages = []) {
    const listeners = {};
    return {
        _conversations: conversations,
        _currentId: currentId,
        _messages: messages,
        getAllConversations: jest.fn(function() { return this._conversations; }),
        getCurrentConversationId: jest.fn(function() { return this._currentId; }),
        getCurrentMessages: jest.fn(function() { return this._messages; }),
        getTotalConversations: jest.fn(function() { return this._conversations.length; }),
        hasMoreConversations: jest.fn(() => false),
        isLoadingConversations: jest.fn(() => false),
        loadConversation: jest.fn(async function(id) {
            const conv = this._conversations.find(c => c.id === id);
            if (!conv) throw new Error(`Conversation ${id} not found`);
            this._currentId = id;
            this._messages = conv.messages || [];
            return conv;
        }),
        addEventListener: jest.fn(function(event, cb) {
            listeners[event] = listeners[event] || [];
            listeners[event].push(cb);
        }),
        notifyConversationListeners: jest.fn((event, data) => {
            (listeners[event] || []).forEach(cb => cb(data));
        }),
    };
}

function makeConv(id, title, { is_favorite = false, is_shared = false, messages = [] } = {}) {
    return { id, title, is_favorite, is_shared, messages, created_at: new Date().toISOString() };
}

// ─── Module loader ────────────────────────────────────────────────────────────

function loadConversationUI() {
    jest.resetModules();
    require('../conversation_ui.js');
    return window.conversationUI;
}

// ─── Global setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
    jest.resetModules();
    buildDOM();

    global.config = { getEndpoints: () => ({ loadConversation: '/api/load-conversation' }) };
    global.getAuthHeaders = () => ({});
    global.sessionId = 'session-test';
    global.fetch = jest.fn(() =>
        Promise.resolve({ ok: true, json: () => Promise.resolve({ message_count: 0 }) })
    );
    global.window.resetSessionForConversationLoad = jest.fn();
    global.window.hydrateChatWithMessages = jest.fn();
    global.window.resetStdoutState = jest.fn();
    global.window.showPromptIdeas = jest.fn();
});

// Helper: find a notification div by type that was added to the body
function getNotification(type) {
    return document.body.querySelector(`.notification.${type}`);
}

// ─── Fix 5: displayConversations DOM reconciliation ──────────────────────────

describe('Fix 5 — displayConversations reconciliation', () => {
    test('renders items on first call', () => {
        const convs = [makeConv('a', 'Alpha'), makeConv('b', 'Beta')];
        global.conversationManager = makeConversationManager(convs);
        loadConversationUI();

        window.conversationUI.displayConversations();

        expect(document.querySelectorAll('.conversation-item').length).toBe(2);
        expect(document.getElementById('conversation-a')).not.toBeNull();
        expect(document.getElementById('conversation-b')).not.toBeNull();
    });

    test('updates title in-place without recreating DOM nodes', () => {
        const convs = [makeConv('a', 'Old Title')];
        global.conversationManager = makeConversationManager(convs);
        loadConversationUI();

        window.conversationUI.displayConversations();
        const firstEl = document.getElementById('conversation-a');

        convs[0].title = 'New Title';
        window.conversationUI.displayConversations();

        const secondEl = document.getElementById('conversation-a');
        expect(secondEl).toBe(firstEl); // same DOM node — not recreated
        expect(secondEl.querySelector('.conversation-title').textContent).toBe('New Title');
    });

    test('removes items no longer in list', () => {
        const convs = [makeConv('a', 'Alpha'), makeConv('b', 'Beta')];
        global.conversationManager = makeConversationManager(convs);
        loadConversationUI();

        window.conversationUI.displayConversations();
        expect(document.getElementById('conversation-b')).not.toBeNull();

        convs.splice(1, 1);
        window.conversationUI.displayConversations();

        expect(document.getElementById('conversation-b')).toBeNull();
        expect(document.getElementById('conversation-a')).not.toBeNull();
    });

    test('reorders DOM nodes to match sorted list', () => {
        const convs = [makeConv('a', 'Alpha'), makeConv('b', 'Beta')];
        global.conversationManager = makeConversationManager(convs);
        loadConversationUI();

        window.conversationUI.displayConversations();

        convs.reverse();
        window.conversationUI.displayConversations();

        const items = document.getElementById('conversationsList').querySelectorAll('.conversation-item');
        expect(items[0].id).toBe('conversation-b');
        expect(items[1].id).toBe('conversation-a');
    });

    test('event listeners bound once — click fires loadConversation only once', () => {
        const convs = [makeConv('a', 'Alpha')];
        const manager = makeConversationManager(convs);
        global.conversationManager = manager;
        loadConversationUI();

        // Render twice (simulates two state updates)
        window.conversationUI.displayConversations();
        window.conversationUI.displayConversations();

        const el = document.getElementById('conversation-a');
        el.click();

        // loadConversation called exactly once despite two renders
        expect(manager.loadConversation).toHaveBeenCalledTimes(1);
        expect(manager.loadConversation).toHaveBeenCalledWith('a');
    });

    test('marks the current conversation with class "current"', () => {
        const convs = [makeConv('a', 'Alpha'), makeConv('b', 'Beta')];
        global.conversationManager = makeConversationManager(convs, 'b');
        loadConversationUI();

        window.conversationUI.displayConversations();

        expect(document.getElementById('conversation-a').classList.contains('current')).toBe(false);
        expect(document.getElementById('conversation-b').classList.contains('current')).toBe(true);
    });

    test('shows empty-state when list is empty', () => {
        global.conversationManager = makeConversationManager([]);
        loadConversationUI();

        window.conversationUI.displayConversations();

        expect(document.querySelector('.empty-state')).not.toBeNull();
        expect(document.querySelectorAll('.conversation-item').length).toBe(0);
    });

    test('replaces empty-state with items when list becomes non-empty', () => {
        const convs = [];
        global.conversationManager = makeConversationManager(convs);
        loadConversationUI();

        window.conversationUI.displayConversations();
        expect(document.querySelector('.empty-state')).not.toBeNull();

        convs.push(makeConv('a', 'Alpha'));
        window.conversationUI.displayConversations();

        expect(document.querySelector('.empty-state')).toBeNull();
        expect(document.getElementById('conversation-a')).not.toBeNull();
    });

    test('updates favorite button and indicator in-place', () => {
        const convs = [makeConv('a', 'Alpha', { is_favorite: false })];
        global.conversationManager = makeConversationManager(convs);
        loadConversationUI();

        window.conversationUI.displayConversations();
        expect(document.querySelector('.favorite-btn').classList.contains('active')).toBe(false);
        expect(document.querySelector('.favorite-indicator')).toBeNull();

        convs[0].is_favorite = true;
        window.conversationUI.displayConversations();

        expect(document.querySelector('.favorite-btn').classList.contains('active')).toBe(true);
        expect(document.querySelector('.favorite-indicator')).not.toBeNull();
    });

    test('shows filtered result count when search yields no match', () => {
        const convs = [makeConv('a', 'Alpha')];
        global.conversationManager = makeConversationManager(convs);
        loadConversationUI();

        window.conversationUI.displayConversations();
        document.getElementById('conversationSearch').value = 'zzz';
        window.conversationUI.displayConversations();

        expect(document.getElementById('conversationCount').textContent).toBe('Showing 0 of 1');
        expect(document.querySelector('.empty-state')).not.toBeNull();
    });
});

// ─── Fix 3: loadConversation atomic sequence ─────────────────────────────────

describe('Fix 3 — loadConversation interpreter sync isolated', () => {
    test('happy path: hydrates messages and shows success notification', async () => {
        const conv = makeConv('c1', 'Test', { messages: [{ id: 'm1', role: 'user', content: 'hi', message_type: 'message' }] });
        global.conversationManager = makeConversationManager([conv]);
        loadConversationUI();

        await window.loadConversation('c1');

        expect(global.window.hydrateChatWithMessages).toHaveBeenCalled();
        expect(getNotification('success')).not.toBeNull();
    });

    test('interpreter sync failure: history still hydrated, warning shown', async () => {
        const conv = makeConv('c1', 'Test', { messages: [{ id: 'm1', role: 'user', content: 'hi', message_type: 'message' }] });
        global.conversationManager = makeConversationManager([conv]);

        // Sync fails
        global.fetch = jest.fn(() =>
            Promise.resolve({ ok: false, status: 503 })
        );

        loadConversationUI();
        await window.loadConversation('c1');

        // History still displayed
        expect(global.window.hydrateChatWithMessages).toHaveBeenCalled();

        // Warning shown, not generic error
        expect(getNotification('warning')).not.toBeNull();
        expect(getNotification('warning').textContent).toContain('contexte interprète non synchronisé');
        expect(getNotification('error')).toBeNull();
    });

    test('DB load failure: messages not hydrated, error notification shown', async () => {
        const convs = [makeConv('c1', 'Test')];
        const manager = makeConversationManager(convs);
        manager.loadConversation = jest.fn(async () => { throw new Error('Network error'); });
        global.conversationManager = manager;
        loadConversationUI();

        await window.loadConversation('c1');

        expect(global.window.hydrateChatWithMessages).not.toHaveBeenCalled();
        expect(getNotification('error')).not.toBeNull();
        expect(getNotification('error').textContent).toContain('Impossible de charger la conversation');
    });
});

// ─── CSV sidebar index ───────────────────────────────────────────────────────

describe('Conversation CSV sidebar index', () => {
    test('renders loaded and created CSV entries from the current conversation', () => {
        const conv = makeConv('c1', 'CSV test', {
            messages: [
                {
                    id: 'm1',
                    role: 'user',
                    message_type: 'file',
                    message_format: 'path',
                    content: '/static/u1/c1/uploads/import.csv',
                    filename: 'import.csv',
                },
                {
                    id: 'm2',
                    role: 'assistant',
                    message_type: 'deliverable',
                    content: JSON.stringify({
                        type: 'export',
                        title: 'Export final',
                        file_url: '/static/u1/c1/uploads/result.csv',
                        filename: 'result.csv',
                    }),
                },
            ],
        });
        global.conversationManager = makeConversationManager([conv], 'c1', conv.messages);
        loadConversationUI();

        window.conversationUI.refreshConversationCsvSidebar();

        const sidebar = document.getElementById('conversationCsvSidebar');
        const items = sidebar.querySelectorAll('.conversation-csv-item');
        expect(sidebar.classList.contains('open')).toBe(true);
        expect(items).toHaveLength(2);
        expect(sidebar.textContent).toContain('import.csv');
        expect(sidebar.textContent).toContain('result.csv');
        expect(sidebar.textContent).toContain('chargé');
        expect(sidebar.textContent).toContain('créé');
    });

    test('shows only one empty-state when the conversation has no CSV', () => {
        const conv = makeConv('c1', 'Empty CSV', { messages: [] });
        global.conversationManager = makeConversationManager([conv], 'c1', []);
        window.getPendingUploads = jest.fn(() => []);
        loadConversationUI();

        window.conversationUI.refreshConversationCsvSidebar();

        const sidebar = document.getElementById('conversationCsvSidebar');
        expect(sidebar.querySelectorAll('.conversation-csv-empty')).toHaveLength(1);
        expect(sidebar.textContent).toContain('Aucun CSV dans cette conversation');
        expect(sidebar.textContent).not.toContain('Sélectionnez un CSV');
        expect(document.getElementById('conversationCsvViewer').textContent).toBe('');
    });

    test('shows a pending uploaded CSV before it is sent as a message', () => {
        const conv = makeConv('c1', 'Pending upload', { messages: [] });
        global.conversationManager = makeConversationManager([conv], 'c1', []);
        window.getPendingUploads = jest.fn(() => ([
            {
                id: 'upload-1',
                name: 'pending.csv',
                path: '/static/u1/c1/uploads/pending.csv',
            },
        ]));
        loadConversationUI();

        window.conversationUI.refreshConversationCsvSidebar();

        const sidebar = document.getElementById('conversationCsvSidebar');
        expect(sidebar.querySelectorAll('.conversation-csv-item')).toHaveLength(1);
        expect(sidebar.textContent).toContain('pending.csv');
        expect(sidebar.textContent).toContain('chargé');
        expect(sidebar.textContent).not.toContain('Aucun CSV dans cette conversation');
    });

    test('keeps a CSV visible after the user message is sent and pending uploads are cleared', () => {
        const conv = makeConv('c1', 'Sent upload', { messages: [] });
        global.conversationManager = makeConversationManager([conv], 'c1', []);
        window.getPendingUploads = jest.fn(() => []);
        window.getFrontendMessages = jest.fn(() => ([
            {
                id: 'msg-1',
                role: 'user',
                attachments: [
                    {
                        id: 'upload-1',
                        name: 'sent.csv',
                        path: '/static/u1/c1/uploads/sent.csv',
                    },
                ],
            },
        ]));
        loadConversationUI();

        window.conversationUI.refreshConversationCsvSidebar();

        const sidebar = document.getElementById('conversationCsvSidebar');
        expect(sidebar.querySelectorAll('.conversation-csv-item')).toHaveLength(1);
        expect(sidebar.textContent).toContain('sent.csv');
        expect(sidebar.textContent).toContain('chargé');
        expect(sidebar.textContent).not.toContain('Aucun CSV dans cette conversation');
    });
});

describe('Conversation CSV preview viewer', () => {
    test('clicking a CSV entry renders a table preview in the sidebar viewer', async () => {
        const conv = makeConv('c1', 'CSV preview', {
            messages: [
                {
                    id: 'm1',
                    role: 'user',
                    message_type: 'file',
                    message_format: 'path',
                    content: '/static/u1/c1/uploads/import.csv',
                    filename: 'import.csv',
                },
            ],
        });
        global.conversationManager = makeConversationManager([conv], 'c1', conv.messages);
        global.fetch = jest.fn(() => Promise.resolve({
            ok: true,
            text: () => Promise.resolve('station,depth\nA,10\nB,20'),
        }));
        loadConversationUI();

        window.conversationUI.refreshConversationCsvSidebar();
        document.querySelector('.conversation-csv-item').click();

        await new Promise(resolve => setTimeout(resolve, 0));

        const viewer = document.getElementById('conversationCsvViewer');
        expect(global.fetch).toHaveBeenCalled();
        expect(viewer.querySelector('table')).not.toBeNull();
        expect(viewer.textContent).toContain('station');
        expect(viewer.textContent).toContain('A');
        expect(viewer.textContent).toContain('10');
    });
});

describe('Conversation CSV selection restoration', () => {
    test('reopens the last viewed CSV after the sidebar is refreshed again', async () => {
        const conv = makeConv('c1', 'CSV restore', {
            messages: [
                {
                    id: 'm1',
                    role: 'user',
                    message_type: 'file',
                    message_format: 'path',
                    content: '/static/u1/c1/uploads/import.csv',
                    filename: 'import.csv',
                },
            ],
        });
        global.conversationManager = makeConversationManager([conv], 'c1', conv.messages);
        global.fetch = jest.fn(() => Promise.resolve({
            ok: true,
            text: () => Promise.resolve('station,depth\nA,10\nB,20'),
        }));
        loadConversationUI();

        window.conversationUI.refreshConversationCsvSidebar();
        document.querySelector('.conversation-csv-item').click();
        await new Promise(resolve => setTimeout(resolve, 0));
        expect(document.getElementById('conversationCsvViewer').textContent).toContain('station');

        // Simulate returning to the same conversation after the UI module reloads.
        loadConversationUI();
        window.conversationUI.refreshConversationCsvSidebar();
        await new Promise(resolve => setTimeout(resolve, 0));

        const viewer = document.getElementById('conversationCsvViewer');
        expect(viewer.querySelector('table')).not.toBeNull();
        expect(viewer.textContent).toContain('A');
        expect(localStorage.getItem('idea-conversation-csv-last-viewed:c1')).toContain('import.csv');
    });
});

describe('Share conversation fallback', () => {
    test('falls back to prompt when clipboard write fails', async () => {
        const conv = makeConv('a', 'Alpha');
        const manager = makeConversationManager([conv]);
        manager.createShareLink = jest.fn(async () => ({
            share_url: '/share/share-token-1',
            share_token: 'share-token-1',
        }));
        global.conversationManager = manager;
        global.prompt = jest.fn();
        Object.defineProperty(global.navigator, 'clipboard', {
            configurable: true,
            value: {
                writeText: jest.fn(() => Promise.reject(new Error('clipboard denied'))),
            },
        });

        loadConversationUI();
        window.conversationUI.displayConversations();

        document.querySelector('.share-btn').click();
        await Promise.resolve();
        await Promise.resolve();

        expect(manager.createShareLink).toHaveBeenCalledWith('a');
        expect(global.prompt).toHaveBeenCalledTimes(1);
        expect(global.prompt.mock.calls[0][0]).toBe('Copy this link to share the conversation:');
        expect(global.prompt.mock.calls[0][1]).toContain('/share/share-token-1');
        expect(getNotification('error')).toBeNull();
    });
});

// ─── Fix: loadConversationIntoInterpreter deduplication ──────────────────────
// Regression guard: concurrent calls (e.g. 5× after stream end) must produce
// exactly ONE POST /load-conversation, not N, to avoid clearing the OI kernel
// N times and triggering N re-upload retries in the frontend.

describe('loadConversationIntoInterpreter deduplication', () => {
    const messages = [{ id: 'm1', role: 'user', content: 'hi' }];

    beforeEach(() => {
        const conv = makeConv('c1', 'Test', { messages });
        global.conversationManager = makeConversationManager([conv]);
        loadConversationUI();
    });

    test('5 concurrent calls produce exactly 1 HTTP request', async () => {
        const calls = await Promise.all([
            window.loadConversation('c1'),
            window.loadConversation('c1'),
            window.loadConversation('c1'),
            window.loadConversation('c1'),
            window.loadConversation('c1'),
        ]);

        // loadConversation calls loadConversationIntoInterpreter internally.
        // fetch is called for: loadConversation DB fetch + 1 interpreter sync (not 5).
        const interpreterSyncCalls = global.fetch.mock.calls.filter(
            call => call[0] === '/api/load-conversation' && call[1]?.method === 'POST'
        );
        expect(interpreterSyncCalls.length).toBe(1);
    });

    test('after first call completes, a subsequent call goes through', async () => {
        await window.loadConversation('c1');
        global.fetch.mockClear();

        await window.loadConversation('c1');

        const interpreterSyncCalls = global.fetch.mock.calls.filter(
            call => call[0] === '/api/load-conversation' && call[1]?.method === 'POST'
        );
        expect(interpreterSyncCalls.length).toBe(1);
    });
});
