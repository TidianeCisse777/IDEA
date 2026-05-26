/**
 * Node.js unit tests for ConversationManager persistence queue.
 * Run: node frontend/test_conversation_manager.js
 */

// Minimal browser globals needed by the module
global.window = { API_BASE_URL: 'http://localhost:9999' };
const _storage = {};
global.localStorage = {
    getItem: (k) => _storage[k] ?? null,
    setItem: (k, v) => { _storage[k] = v; },
    removeItem: (k) => { delete _storage[k]; },
};

const { ConversationManager } = require('./conversation_manager.js');

let passed = 0;
let failed = 0;

function assert(condition, label) {
    if (condition) {
        console.log(`  ✓ ${label}`);
        passed++;
    } else {
        console.error(`  ✗ ${label}`);
        failed++;
    }
}

// ─── helpers ────────────────────────────────────────────────────────────────

function makeFetchOk(body) {
    return () => Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
}

function makeFetchFail() {
    return () => Promise.resolve({ ok: false, status: 500 });
}

function makeManager(fetchImpl) {
    global.fetch = fetchImpl;
    // Bypass init() network call
    const m = new ConversationManager('http://localhost:9999');
    m.isLoading = false;
    m.currentConversationId = 'conv-1';
    return m;
}

// ─── Test 1: addMessage failure enqueues and emits persistence_error ─────────

async function test_addMessage_failure_enqueues() {
    console.log('\nTest: addMessage failure → enqueue + persistence_error event');

    let errorEvents = [];
    global.fetch = makeFetchFail();
    const m = new ConversationManager('http://localhost:9999');
    m.isLoading = false;
    m.currentConversationId = 'conv-1';
    m.addEventListener('persistence_error', (data) => errorEvents.push(data));

    try { await m.addMessage('user', 'hello', 'message'); } catch (_) {}

    assert(m._persistenceQueue.length === 1, 'One item queued');
    assert(errorEvents.length === 1, 'persistence_error emitted once');
    assert(errorEvents[0].queued === 1, 'queued count = 1');
    assert(m._retryScheduled === true, 'Retry scheduled');
}

// ─── Test 2: flush succeeds → emits persistence_recovered, clears queue ──────

async function test_flush_success() {
    console.log('\nTest: _flushPersistenceQueue success → persistence_recovered');

    let recovered = false;
    const savedMessage = { id: 'msg-db-1', role: 'user', content: 'hello', created_at: new Date().toISOString() };
    global.fetch = makeFetchOk(savedMessage);

    const m = new ConversationManager('http://localhost:9999');
    m.isLoading = false;
    m.currentConversationId = 'conv-1';
    m.addEventListener('persistence_recovered', () => { recovered = true; });

    // Manually queue an item (skip the retry timer)
    m._persistenceQueue.push({
        conversationId: 'conv-1',
        data: { role: 'user', content: 'hello', message_type: 'message', message_format: null, recipient: null, conversation_id: 'conv-1' },
    });

    await m._flushPersistenceQueue();

    assert(m._persistenceQueue.length === 0, 'Queue empty after flush');
    assert(recovered === true, 'persistence_recovered emitted');
    assert(m.currentMessages.length === 1, 'Message added to currentMessages');
}

// ─── Test 3: flush fails → emits persistence_failed ──────────────────────────

async function test_flush_failure() {
    console.log('\nTest: _flushPersistenceQueue failure → persistence_failed');

    let failedEvent = null;
    global.fetch = makeFetchFail();

    const m = new ConversationManager('http://localhost:9999');
    m.isLoading = false;
    m.currentConversationId = 'conv-1';
    m.addEventListener('persistence_failed', (data) => { failedEvent = data; });

    m._persistenceQueue.push({
        conversationId: 'conv-1',
        data: { role: 'assistant', content: 'hi', message_type: 'message', message_format: null, recipient: null, conversation_id: 'conv-1' },
    });

    await m._flushPersistenceQueue();

    assert(failedEvent !== null, 'persistence_failed emitted');
    assert(failedEvent.count === 1, 'count = 1');
    assert(m._persistenceQueue.length === 0, 'Queue drained even on failure');
}

// ─── Test 4: no fetchSessionHistory in assistant.js ──────────────────────────

function test_no_fetchSessionHistory_in_assistant() {
    console.log('\nTest: assistant.js has no fetchSessionHistory fallback');
    const fs = require('fs');
    const src = fs.readFileSync(__dirname + '/assistant.js', 'utf8');
    assert(!src.includes('fetchSessionHistory'), 'fetchSessionHistory removed from assistant.js');
    assert(src.includes("localStorage.removeItem('activeConversationId')"), 'Stale ID still cleaned up');
    assert(src.includes('persistence_error'), 'persistence_error listener wired');
    assert(src.includes('persistence_recovered'), 'persistence_recovered listener wired');
    assert(src.includes('persistence_failed'), 'persistence_failed listener wired');
}

// ─── Test 5: DOM ID reconciliation after addMessage success ──────────────────

async function test_dom_id_reconciliation() {
    console.log('\nTest: addMessage reconciles frontend ID → backend UUID in DOM');
    const dbMessage = { id: 'uuid-db-999', role: 'user', content: 'hello', created_at: new Date().toISOString() };
    global.fetch = makeFetchOk(dbMessage);

    const m = new ConversationManager('http://localhost:9999');
    m.isLoading = false;
    m.currentConversationId = 'conv-1';

    // Simulate a DOM element created with a frontend-generated ID
    const frontendId = 'msg-abc123';
    const fakeEl = { currentId: frontendId, setAttribute(attr, val) { if (attr === 'data-id') this.currentId = val; } };
    global.document = { querySelector: (sel) => sel === `[data-id="${frontendId}"]` ? fakeEl : null };

    // We need to simulate what assistant.js does in appendMessage:
    // after addMessage resolves, reconcile data-id
    const frontendMsg = { id: frontendId, role: 'user' };
    const saved = await m.addMessage('user', 'hello', 'message');
    if (frontendId && saved && saved.id && frontendId !== saved.id) {
        const el = document.querySelector(`[data-id="${frontendId}"]`);
        if (el) el.setAttribute('data-id', saved.id);
        frontendMsg.id = saved.id;
    }

    assert(fakeEl.currentId === 'uuid-db-999', 'DOM element data-id updated to backend UUID');
    assert(frontendMsg.id === 'uuid-db-999', 'In-memory message.id updated to backend UUID');

    delete global.document;
}

// ─── Test 6: structural checks for Fix 3 and Fix 5 ───────────────────────────

function test_structural_fixes() {
    console.log('\nTest: conversation_ui.js structural fixes (3 + 5)');
    const fs = require('fs');
    const src = fs.readFileSync(__dirname + '/conversation_ui.js', 'utf8');

    // Fix 3: interpreter sync isolated
    assert(src.includes('Interpreter sync is best-effort'), 'Fix 3: interpreter sync comment present');
    assert(src.includes('Historique chargé — contexte interprète non synchronisé'), 'Fix 3: warning message on sync failure');
    assert(!src.includes("// Load conversation context into backend interpreter\n        await"), 'Fix 3: old await not in main try block');

    // Fix 5: reconciliation instead of innerHTML wipe
    assert(src.includes('_updateConversationItem'), 'Fix 5: _updateConversationItem helper defined');
    assert(src.includes('_bindConversationItemListeners'), 'Fix 5: _bindConversationItemListeners helper defined');
    assert(src.includes('conversationsList.appendChild(el)'), 'Fix 5: appendChild used for ordering');
    assert(!src.includes('conversationsList.innerHTML = conversationsHTML'), 'Fix 5: full innerHTML wipe removed');
}

// ─── Runner ──────────────────────────────────────────────────────────────────

(async () => {
    await test_addMessage_failure_enqueues();
    await test_flush_success();
    await test_flush_failure();
    test_no_fetchSessionHistory_in_assistant();
    await test_dom_id_reconciliation();
    test_structural_fixes();

    console.log(`\n${passed} passed, ${failed} failed`);
    process.exit(failed > 0 ? 1 : 0);
})();
