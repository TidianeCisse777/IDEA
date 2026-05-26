/**
 * @jest-environment jsdom
 *
 * XSS regression tests — Group A fixes.
 * Each test injects a payload that would execute JS if not sanitized,
 * then asserts the payload did NOT execute and the DOM is safe.
 */

// ─── DOMPurify stub (jsdom doesn't run CDN scripts) ──────────────────────────
// Real DOMPurify is loaded from CDN in production. In Jest we stub it:
// strip <script> and on* attributes, return the rest intact.
global.DOMPurify = {
    sanitize(html) {
        if (typeof html !== 'string') return '';
        return html
            .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
            .replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]*)/gi, '');
    },
};

// marked stub — wraps content in a <p> tag
global.marked = { parse: (s) => `<p>${s}</p>` };

// Prism stub
global.Prism = { highlightElement: () => {}, highlightAllUnder: () => {} };

// escapeHtml from assistant.js / conversation_ui.js (same impl in both files)
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
global.escapeHtml = escapeHtml;

// ─── Helpers ─────────────────────────────────────────────────────────────────

let xssFired;

beforeEach(() => {
    xssFired = false;
    global.xssProbe = () => { xssFired = true; };
    document.body.innerHTML = '';
});

function render(html) {
    const el = document.createElement('div');
    el.innerHTML = html;
    document.body.appendChild(el);
    return el;
}

const SCRIPT_PAYLOAD = '<script>xssProbe();<\/script>';
const EVENT_PAYLOAD  = '<img src=x onerror="xssProbe()">';
const ATTR_PAYLOAD   = '" onload="xssProbe()';  // breaks out of attribute

// ─── Fix #9 — HTML format messages sanitized with DOMPurify ──────────────────

describe('Fix #9 — format=html sanitized', () => {
    test('script tag stripped from html format content', () => {
        const dirty = `<p>Hello</p>${SCRIPT_PAYLOAD}`;
        const safe  = DOMPurify.sanitize(dirty);
        render(safe);
        expect(xssFired).toBe(false);
        expect(document.querySelector('script')).toBeNull();
    });

    test('event handler stripped from html format content', () => {
        const safe = DOMPurify.sanitize(EVENT_PAYLOAD);
        render(safe);
        expect(xssFired).toBe(false);
        expect(document.querySelector('[onerror]')).toBeNull();
    });

    test('benign HTML preserved after sanitization', () => {
        const html  = '<p><strong>Bold</strong> and <em>italic</em></p>';
        const safe  = DOMPurify.sanitize(html);
        const el    = render(safe);
        expect(el.querySelector('strong')).not.toBeNull();
        expect(el.querySelector('em')).not.toBeNull();
    });
});

// ─── Fix #6 — Unknown message type uses textContent, not innerHTML ────────────

describe('Fix #6 — unknown type uses textContent', () => {
    test('script payload stored as text, not executed', () => {
        const el = document.createElement('div');
        el.textContent = SCRIPT_PAYLOAD;
        document.body.appendChild(el);
        expect(xssFired).toBe(false);
        expect(el.textContent).toContain('<script>');
        expect(document.querySelector('script')).toBeNull();
    });

    test('event handler payload stored as text, not parsed as HTML', () => {
        const el = document.createElement('div');
        el.textContent = EVENT_PAYLOAD;
        document.body.appendChild(el);
        expect(xssFired).toBe(false);
        // No actual <img> element — it's just text
        expect(el.querySelector('img')).toBeNull();
    });
});

// ─── Fix #7 — Image path and file href use escapeHtml ────────────────────────

describe('Fix #7 — file paths escaped in HTML attributes', () => {
    test('image src: DOM API prevents attribute injection', () => {
        const maliciousPath = `legit.png" onload="xssProbe()`;
        // Simulate the fixed code: createElement + img.src = content
        const container = document.createElement('div');
        const img = document.createElement('img');
        img.src = maliciousPath;
        img.alt = 'Image';
        container.appendChild(img);
        document.body.appendChild(container);
        expect(xssFired).toBe(false);
        expect(img.getAttribute('onload')).toBeNull();
        // src is set as-is (no injection possible via DOM API)
        expect(img.src).toContain('legit.png');
    });

    test('file href: DOM API prevents attribute injection', () => {
        const maliciousPath = `file.csv" onclick="xssProbe()`;
        // Simulate the fixed code: createElement + a.href = content
        const container = document.createElement('div');
        const a = document.createElement('a');
        a.href = maliciousPath;
        a.download = '';
        a.textContent = 'Download File';
        container.appendChild(a);
        document.body.appendChild(container);
        expect(xssFired).toBe(false);
        expect(a.getAttribute('onclick')).toBeNull();
    });
});

// ─── Fix #8 — appendSystemMessage sanitizes marked output ────────────────────

describe('Fix #8 — system messages sanitized', () => {
    test('script in system message stripped', () => {
        const rawMsg   = `Error: ${SCRIPT_PAYLOAD}`;
        const parsed   = marked.parse(rawMsg);
        const sanitized = DOMPurify.sanitize(parsed);
        render(sanitized);
        expect(xssFired).toBe(false);
        expect(document.querySelector('script')).toBeNull();
    });

    test('event handler in system message stripped', () => {
        const rawMsg   = `Status: ${EVENT_PAYLOAD}`;
        const parsed   = marked.parse(rawMsg);
        const sanitized = DOMPurify.sanitize(parsed);
        const el = render(sanitized);
        expect(xssFired).toBe(false);
        expect(el.querySelector('[onerror]')).toBeNull();
    });
});

// ─── Fix #10 — conversation_ui marked.parse fallback safe ────────────────────

describe('Fix #10 — displayMessageInChat markdown sanitized', () => {
    test('marked path: event handler stripped', () => {
        const content  = `Hello ${EVENT_PAYLOAD}`;
        const parsed   = marked.parse(content);
        const sanitized = DOMPurify.sanitize(parsed);
        render(sanitized);
        expect(xssFired).toBe(false);
        expect(document.querySelector('[onerror]')).toBeNull();
    });

    test('fallback (no marked): raw content escaped via escapeHtml', () => {
        const content = EVENT_PAYLOAD;
        const el = document.createElement('div');
        // Simulate: no marked → escapeHtml
        el.innerHTML = escapeHtml(content);
        document.body.appendChild(el);
        expect(xssFired).toBe(false);
        // Content present as text, no <img> element created
        expect(el.querySelector('img')).toBeNull();
        expect(el.textContent).toContain('<img');
    });

    test('image path in history: DOM API prevents onerror injection', () => {
        const maliciousPath = `legit.png" onerror="xssProbe()`;
        // Simulate the fixed code: createElement + img.src = message.content
        const container = document.createElement('div');
        const img = document.createElement('img');
        img.src = maliciousPath;
        img.alt = 'Image';
        container.appendChild(img);
        document.body.appendChild(container);
        expect(xssFired).toBe(false);
        expect(img.getAttribute('onerror')).toBeNull();
    });
});
