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

// ─── Runner ──────────────────────────────────────────────────────────────────

(async () => {
    await test_addMessage_failure_enqueues();
    await test_flush_success();
    await test_flush_failure();
    test_no_fetchSessionHistory_in_assistant();

    console.log(`\n${passed} passed, ${failed} failed`);
    process.exit(failed > 0 ? 1 : 0);
})();
