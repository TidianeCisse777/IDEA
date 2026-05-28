/**
 * @jest-environment jsdom
 *
 * Message rendering tests — displayMessageInChat (conversation_ui.js).
 *
 * Tests that each message type (text, code, image) is rendered correctly
 * and that HTML is sanitized to prevent XSS.
 */

// ── Stubs for CDN deps ────────────────────────────────────────────────────────

global.marked = { parse: (s) => `<p>${s}</p>` };

global.DOMPurify = {
    sanitize(html) {
        if (typeof html !== 'string') return '';
        // Strip <script> and on* event handlers — mirrors real DOMPurify
        return html
            .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
            .replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]*)/gi, '');
    },
};

global.Prism = { highlightAllUnder: jest.fn() };

// ── DOM scaffold ──────────────────────────────────────────────────────────────

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
        <div id="chatDisplay"></div>
    `;
}

// ── Module loader ─────────────────────────────────────────────────────────────

function loadModule() {
    jest.resetModules();
    global.conversationManager = {
        getAllConversations: () => [],
        getCurrentConversationId: () => null,
        getCurrentMessages: () => [],
        getTotalConversations: () => 0,
        hasMoreConversations: () => false,
        isLoadingConversations: () => false,
        addEventListener: jest.fn(),
    };
    global.config = { getEndpoints: () => ({}) };
    global.getAuthHeaders = () => ({});
    global.sessionId = 'test-session';
    global.fetch = jest.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve({ message_count: 0 }) }));
    global.window.resetSessionForConversationLoad = jest.fn();
    global.window.hydrateChatWithMessages = jest.fn();
    global.window.resetStdoutState = jest.fn();
    global.window.showPromptIdeas = jest.fn();
    require('../conversation_ui.js');
    return window.conversationUI;
}

function msg(type, format, content, role = 'assistant') {
    return { id: 'msg-1', role, message_type: type, message_format: format, content };
}

let xssFired;
beforeEach(() => {
    xssFired = false;
    global.xssProbe = () => { xssFired = true; };
    buildDOM();
    loadModule();
});

// ── Behavior 1: text messages are rendered as markdown ────────────────────────

describe('Text messages', () => {
    test('message type renders markdown content into chatDisplay', () => {
        window.conversationUI.displayMessageInChat(msg('message', null, 'Hello **world**'));
        const chat = document.getElementById('chatDisplay');
        expect(chat.querySelector('.message')).not.toBeNull();
        expect(chat.querySelector('.content').innerHTML).toContain('<p>');
    });

    test('message type with role "user" gets user CSS class', () => {
        window.conversationUI.displayMessageInChat(msg('message', null, 'I am user', 'user'));
        expect(document.querySelector('.message.user')).not.toBeNull();
    });

    test('message type with role "assistant" gets assistant CSS class', () => {
        window.conversationUI.displayMessageInChat(msg('message', null, 'I am LLM', 'assistant'));
        expect(document.querySelector('.message.assistant')).not.toBeNull();
    });
});

// ── Behavior 2: code messages render with syntax class ────────────────────────

describe('Code messages', () => {
    test('code message with python format renders pre>code with language class', () => {
        window.conversationUI.displayMessageInChat(msg('code', 'python', 'print("hello")'));
        const code = document.querySelector('code.language-python');
        expect(code).not.toBeNull();
        expect(code.textContent).toContain('print("hello")');
    });

    test('code content is escaped — no raw HTML injection', () => {
        window.conversationUI.displayMessageInChat(
            msg('code', 'python', '<script>xssProbe();</script>')
        );
        // The script text should appear as text, not as a DOM element
        expect(xssFired).toBe(false);
        expect(document.querySelector('script')).toBeNull();
    });

    test('code message with html format is sanitized by DOMPurify', () => {
        window.conversationUI.displayMessageInChat(
            msg('code', 'html', '<b>Safe</b><script>xssProbe();</script>')
        );
        expect(xssFired).toBe(false);
        expect(document.querySelector('script')).toBeNull();
        // Benign HTML is preserved
        expect(document.querySelector('b')).not.toBeNull();
    });
});

// ── Behavior 3: image messages render an <img> tag ───────────────────────────

describe('Image messages (graphs/charts)', () => {
    test('image with format "path" renders an img with the given src', () => {
        window.conversationUI.displayMessageInChat(
            msg('image', 'path', '/static/u1/s1/chart.png')
        );
        const img = document.querySelector('img');
        expect(img).not.toBeNull();
        expect(img.src).toContain('chart.png');
    });

    test('image with format "base64.png" renders a data-URI img', () => {
        const b64 = 'iVBORw0KGgo=';
        window.conversationUI.displayMessageInChat(msg('image', 'base64.png', b64));
        const img = document.querySelector('img');
        expect(img).not.toBeNull();
        expect(img.src).toContain('data:image/png;base64,');
        expect(img.src).toContain(b64);
    });
});

// ── Behavior 4: console messages are hidden by default ───────────────────────

describe('Console messages', () => {
    test('console message is hidden (style display none)', () => {
        window.conversationUI.displayMessageInChat(msg('console', null, 'some output'));
        const content = document.querySelector('[data-type="console"]');
        expect(content).not.toBeNull();
        expect(content.style.display).toBe('none');
    });

    test('console content is escaped — no HTML injection', () => {
        window.conversationUI.displayMessageInChat(
            msg('console', null, '<script>xssProbe();</script>')
        );
        expect(xssFired).toBe(false);
        expect(document.querySelector('script')).toBeNull();
    });
});

// ── Behavior 5: multi-turn ordering in chatDisplay ───────────────────────────

describe('Multi-turn message ordering in DOM', () => {
    test('messages are appended in order: user, assistant, user', () => {
        window.conversationUI.displayMessageInChat(msg('message', null, 'Turn 1', 'user'));
        window.conversationUI.displayMessageInChat(msg('message', null, 'Reply 1', 'assistant'));
        window.conversationUI.displayMessageInChat(msg('message', null, 'Turn 2', 'user'));

        const divs = document.querySelectorAll('#chatDisplay .message');
        expect(divs).toHaveLength(3);
        expect(divs[0].classList.contains('user')).toBe(true);
        expect(divs[1].classList.contains('assistant')).toBe(true);
        expect(divs[2].classList.contains('user')).toBe(true);
    });

    test('code block between two messages preserves order', () => {
        window.conversationUI.displayMessageInChat(msg('message', null, 'Question', 'user'));
        window.conversationUI.displayMessageInChat(msg('code', 'python', 'x = 1', 'assistant'));
        window.conversationUI.displayMessageInChat(msg('message', null, 'Result', 'assistant'));

        const divs = document.querySelectorAll('#chatDisplay .message');
        expect(divs).toHaveLength(3);
        expect(divs[1].querySelector('code.language-python')).not.toBeNull();
    });

    test('image (chart) followed by a user message keeps correct order', () => {
        window.conversationUI.displayMessageInChat(msg('image', 'path', '/static/chart.png', 'assistant'));
        window.conversationUI.displayMessageInChat(msg('message', null, 'Can you explain?', 'user'));

        const divs = document.querySelectorAll('#chatDisplay .message');
        expect(divs).toHaveLength(2);
        expect(divs[0].querySelector('img')).not.toBeNull();
        expect(divs[1].classList.contains('user')).toBe(true);
    });
});
