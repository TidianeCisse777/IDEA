/**
 * @jest-environment jsdom
 *
 * message-renderer — pure helper functions for math, escaping, attachment parsing.
 */

// Stub globals referenced in module-level code paths
global.marked = { parse: (s) => `<p>${s}</p>` };
global.DOMPurify = { sanitize: (s) => s };
global.chatDisplay = { scrollTop: 0, scrollHeight: 0 };
global.messages = [];

const {
    protectMath,
    restoreMath,
    countUnescapedSequence,
    hasBalancedMath,
    hasMathDelimiters,
    generateId,
    escapeHtml,
    formatAttachmentLabel,
    extractAttachmentInfoFromContent,
    isInspectionReportMessage,
    extractReportTitle,
    wrapInspectionReportCollapsible,
} = require('../message-renderer.js');

describe('generateId', () => {
    test('returns string with prefix and dash', () => {
        const id = generateId('msg');
        expect(id).toMatch(/^msg-[a-z0-9]+$/);
    });

    test('produces unique values across calls', () => {
        const ids = new Set();
        for (let i = 0; i < 200; i++) ids.add(generateId('x'));
        expect(ids.size).toBe(200);
    });
});

describe('escapeHtml', () => {
    test('escapes the 5 reserved characters', () => {
        expect(escapeHtml('<>&"\'')).toBe('&lt;&gt;&amp;&quot;&#039;');
    });

    test('leaves plain text unchanged', () => {
        expect(escapeHtml('hello world 123')).toBe('hello world 123');
    });

    test('escapes script-injection attempts', () => {
        const result = escapeHtml('<script>alert("x")</script>');
        expect(result).not.toContain('<script>');
        expect(result).toContain('&lt;script&gt;');
    });
});

describe('protectMath / restoreMath', () => {
    test('round-trips $$...$$ display math without loss', () => {
        const original = 'before $$x^2 + y^2$$ after';
        const { text, store } = protectMath(original);
        expect(text).not.toContain('$$x^2');
        expect(store).toHaveLength(1);
        expect(restoreMath(text, store)).toBe(original);
    });

    test('round-trips inline $...$ math', () => {
        const original = 'value is $x = 1$ here';
        const { text, store } = protectMath(original);
        expect(store).toHaveLength(1);
        expect(restoreMath(text, store)).toBe(original);
    });

    test('round-trips \\[...\\] and \\(...\\)', () => {
        const original = '\\[a+b\\] inline \\(c-d\\)';
        const { text, store } = protectMath(original);
        expect(store).toHaveLength(2);
        expect(restoreMath(text, store)).toBe(original);
    });
});

describe('countUnescapedSequence', () => {
    test('counts $$ occurrences', () => {
        expect(countUnescapedSequence('$$a$$ $$b$$', '$$')).toBe(4);
    });

    test('skips escaped sequences', () => {
        expect(countUnescapedSequence('\\$$ $$', '$$')).toBe(1);
    });
});

describe('hasBalancedMath', () => {
    test('returns true when delimiters balanced', () => {
        expect(hasBalancedMath('$$x$$ \\[y\\] \\(z\\)')).toBe(true);
    });

    test('returns false when $$ open without close', () => {
        expect(hasBalancedMath('$$x')).toBe(false);
    });

    test('returns false on \\[ without \\]', () => {
        expect(hasBalancedMath('\\[unmatched')).toBe(false);
    });
});

describe('hasMathDelimiters', () => {
    test('detects $$...$$', () => {
        expect(hasMathDelimiters('text $$a$$ text')).toBe(true);
    });

    test('detects inline $...$', () => {
        expect(hasMathDelimiters('value $x$')).toBe(true);
    });

    test('detects \\[...\\]', () => {
        expect(hasMathDelimiters('\\[block\\]')).toBe(true);
    });

    test('returns false for plain text', () => {
        expect(hasMathDelimiters('no math here, just $5')).toBe(false);
    });
});

describe('formatAttachmentLabel', () => {
    test('returns "File" for count 1', () => {
        expect(formatAttachmentLabel(1)).toBe('File');
    });

    test('returns "Files" for count > 1', () => {
        expect(formatAttachmentLabel(3)).toBe('Files');
    });

    test('returns "Files" for count 0', () => {
        expect(formatAttachmentLabel(0)).toBe('Files');
    });
});

describe('extractAttachmentInfoFromContent', () => {
    test('extracts a single File label from first line', () => {
        const info = extractAttachmentInfoFromContent('File: report.pdf\n\nrest of message');
        expect(info).toEqual({
            label: 'File',
            names: 'report.pdf',
            remaining: 'rest of message',
        });
    });

    test('extracts Files (plural) label', () => {
        const info = extractAttachmentInfoFromContent('Files: a.csv, b.csv\nbody');
        expect(info.label).toBe('Files');
        expect(info.names).toBe('a.csv, b.csv');
    });

    test('returns null when content has no attachment header', () => {
        expect(extractAttachmentInfoFromContent('hello world')).toBeNull();
    });

    test('returns null for non-string input', () => {
        expect(extractAttachmentInfoFromContent(null)).toBeNull();
        expect(extractAttachmentInfoFromContent(42)).toBeNull();
    });
});

describe('isInspectionReportMessage', () => {
    test('detects the inspection report header', () => {
        expect(isInspectionReportMessage("# RAPPORT D'INSPECTION\nfoo")).toBe(true);
    });

    test('returns false for ordinary markdown', () => {
        expect(isInspectionReportMessage('Hello **world**')).toBe(false);
    });
});

describe('extractReportTitle', () => {
    test('extracts title from <!-- report-title: ... --> comment', () => {
        const raw = "# RAPPORT D'INSPECTION\n<!-- report-title: 📄 bio_oracle (9 × 4) — modèle environnemental -->\n\n- **file_path**...";
        expect(extractReportTitle(raw)).toBe('📄 bio_oracle (9 × 4) — modèle environnemental');
    });

    test('returns fallback when comment absent', () => {
        const raw = "# RAPPORT D'INSPECTION\n\n- **file_path** : `/tmp/x.csv`";
        expect(extractReportTitle(raw)).toBe('📄 Rapport d\'inspection');
    });
});

describe('wrapInspectionReportCollapsible', () => {
    test('wraps contentDiv in a collapsed container', () => {
        const container = document.createElement('div');
        container.innerHTML = '<h1>RAPPORT</h1><p>content</p>';
        wrapInspectionReportCollapsible(container, '📄 bio_oracle (9 × 4) — modèle environnemental');
        expect(container.querySelector('.report-toggle')).not.toBeNull();
        expect(container.querySelector('.report-body')).not.toBeNull();
    });

    test('report body is hidden by default', () => {
        const container = document.createElement('div');
        container.innerHTML = '<p>content</p>';
        wrapInspectionReportCollapsible(container, '📄 test');
        const body = container.querySelector('.report-body');
        expect(body.style.display).toBe('none');
    });

    test('clicking toggle shows and hides body', () => {
        const container = document.createElement('div');
        container.innerHTML = '<p>content</p>';
        wrapInspectionReportCollapsible(container, '📄 test');
        const toggle = container.querySelector('.report-toggle');
        const body = container.querySelector('.report-body');
        toggle.click();
        expect(body.style.display).toBe('block');
        toggle.click();
        expect(body.style.display).toBe('none');
    });

    test('toggle button shows the report title', () => {
        const container = document.createElement('div');
        container.innerHTML = '<p>content</p>';
        wrapInspectionReportCollapsible(container, '📄 bio_oracle (9 × 4) — modèle environnemental');
        const toggle = container.querySelector('.report-toggle');
        expect(toggle.textContent).toContain('bio_oracle');
    });

    test('toggle button contains RAPPORT DÉTAILLÉ label', () => {
        const container = document.createElement('div');
        container.innerHTML = '<p>content</p>';
        wrapInspectionReportCollapsible(container, '📄 test');
        const label = container.querySelector('.report-toggle-label');
        expect(label).not.toBeNull();
        expect(label.textContent).toContain('RAPPORT');
    });

    test('expanded title shows RAPPORT DÉTAILLÉ', () => {
        const container = document.createElement('div');
        container.innerHTML = '<p>content</p>';
        wrapInspectionReportCollapsible(container, '📄 bio_oracle (9 × 4)');
        const expandedTitle = container.querySelector('.report-expanded-title');
        expect(expandedTitle).not.toBeNull();
        expect(expandedTitle.textContent).toBe('RAPPORT DÉTAILLÉ');
    });

    test('expanded subtitle shows file title without emoji', () => {
        const container = document.createElement('div');
        container.innerHTML = '<p>content</p>';
        wrapInspectionReportCollapsible(container, '📄 bio_oracle (9 × 4)');
        const sub = container.querySelector('.report-expanded-subtitle');
        expect(sub).not.toBeNull();
        expect(sub.textContent).toBe('bio_oracle (9 × 4)');
        expect(sub.textContent).not.toContain('📄');
    });

    test('toggle title has no emoji', () => {
        const container = document.createElement('div');
        container.innerHTML = '<p>content</p>';
        wrapInspectionReportCollapsible(container, '📄 bio_oracle (9 × 4)');
        const toggleTitle = container.querySelector('.report-toggle-title');
        expect(toggleTitle.textContent).not.toContain('📄');
        expect(toggleTitle.textContent).toContain('bio_oracle');
    });
});
