/**
 * @jest-environment jsdom
 *
 * code-runner — pure helpers for chunk normalization and message classification.
 */

const {
    normalizeStdStreamMessage,
    normalizeIncomingChunk,
    getChunkKey,
    getFormatKey,
    isShellCodeMessage,
    isTelemetryConsoleMessage,
    isConsoleOutputMessage,
    shouldTrackCodeMessage,
    shouldTriggerInspectionIndicator,
} = require('../code-runner.js');

describe('normalizeIncomingChunk', () => {
    test('message + stdout recipient → console with stdout format', () => {
        const c = normalizeIncomingChunk({ type: 'message', recipient: 'stdout' });
        expect(c.type).toBe('console');
        expect(c.format).toBe('stdout');
    });

    test('text + stderr recipient → console with stderr format', () => {
        const c = normalizeIncomingChunk({ type: 'text', recipient: 'STDERR' });
        expect(c.type).toBe('console');
        expect(c.format).toBe('stderr');
    });

    test('console without format + recipient stderr → format=stderr', () => {
        const c = normalizeIncomingChunk({ type: 'console', recipient: 'stderr' });
        expect(c.format).toBe('stderr');
    });

    test('console without recipient or format → format=output', () => {
        const c = normalizeIncomingChunk({ type: 'console' });
        expect(c.format).toBe('output');
    });

    test('lowercases recipient', () => {
        const c = normalizeIncomingChunk({ type: 'console', recipient: 'STDOUT' });
        expect(c.recipient).toBe('stdout');
    });

    test('preserves non-standard message types', () => {
        const c = normalizeIncomingChunk({ type: 'image', format: 'base64' });
        expect(c.type).toBe('image');
        expect(c.format).toBe('base64');
    });

    test('returns falsy input as-is', () => {
        expect(normalizeIncomingChunk(null)).toBeNull();
        expect(normalizeIncomingChunk(undefined)).toBeUndefined();
    });
});

describe('normalizeStdStreamMessage', () => {
    test('uses message_type/message_format when type/format missing', () => {
        const m = normalizeStdStreamMessage({
            message_type: 'message',
            message_format: 'plain',
            message_recipient: 'stdout',
        });
        expect(m.type).toBe('console');
        expect(m.format).toBe('plain');
        expect(m.recipient).toBe('stdout');
    });

    test('returns falsy input unchanged', () => {
        expect(normalizeStdStreamMessage(null)).toBeNull();
    });
});

describe('getChunkKey', () => {
    test('combines role and type with colon', () => {
        expect(getChunkKey({ role: 'assistant', type: 'message' })).toBe('assistant:message');
    });

    test('handles missing role and type', () => {
        expect(getChunkKey({})).toBe(':');
    });
});

describe('getFormatKey', () => {
    test('returns format when present', () => {
        expect(getFormatKey({ format: 'python' })).toBe('python');
    });

    test('falls back to recipient when format missing', () => {
        expect(getFormatKey({ recipient: 'stderr' })).toBe('stderr');
    });

    test('returns __default__ when neither present', () => {
        expect(getFormatKey({})).toBe('__default__');
    });

    test('handles falsy chunk', () => {
        expect(getFormatKey(null)).toBe('__default__');
    });
});

describe('isShellCodeMessage', () => {
    test('true for bash format', () => {
        expect(isShellCodeMessage({ type: 'code', format: 'bash' })).toBe(true);
    });

    test('true for shell format (case-insensitive)', () => {
        expect(isShellCodeMessage({ type: 'code', format: 'SHELL' })).toBe(true);
    });

    test('false for python format', () => {
        expect(isShellCodeMessage({ type: 'code', format: 'python' })).toBe(false);
    });

    test('false when type is not code', () => {
        expect(isShellCodeMessage({ type: 'message', format: 'bash' })).toBe(false);
    });
});

describe('isTelemetryConsoleMessage', () => {
    test('true for active_line format', () => {
        expect(isTelemetryConsoleMessage({ type: 'console', format: 'active_line' })).toBe(true);
    });

    test('true for execution counter format like "42/100"', () => {
        expect(isTelemetryConsoleMessage({
            type: 'console',
            format: 'execution',
            content: '42/100',
        })).toBe(true);
    });

    test('true for content "line 5"', () => {
        expect(isTelemetryConsoleMessage({ type: 'console', content: 'line 5' })).toBe(true);
    });

    test('false for normal console output', () => {
        expect(isTelemetryConsoleMessage({
            type: 'console',
            format: 'output',
            content: 'Hello world',
        })).toBe(false);
    });

    test('false when type is not console', () => {
        expect(isTelemetryConsoleMessage({ type: 'message', format: 'active_line' })).toBe(false);
    });
});

describe('isConsoleOutputMessage', () => {
    test('true for console type with regular format', () => {
        expect(isConsoleOutputMessage({ type: 'console', format: 'output' })).toBe(true);
    });

    test('false for telemetry active_line', () => {
        expect(isConsoleOutputMessage({ type: 'console', format: 'active_line' })).toBe(false);
    });

    test('true for message type with stdout recipient', () => {
        expect(isConsoleOutputMessage({ type: 'message', recipient: 'stdout' })).toBe(true);
    });

    test('false for random other message', () => {
        expect(isConsoleOutputMessage({ type: 'image', format: 'png' })).toBe(false);
    });

    test('false for falsy input', () => {
        expect(isConsoleOutputMessage(null)).toBe(false);
    });
});

describe('shouldTrackCodeMessage', () => {
    test('true for code message from assistant', () => {
        expect(shouldTrackCodeMessage({ type: 'code', role: 'assistant', format: 'python' })).toBe(true);
    });

    test('false for user code message', () => {
        expect(shouldTrackCodeMessage({ type: 'code', role: 'user', format: 'python' })).toBe(false);
    });

    test('false for html code (rendered, not executed)', () => {
        expect(shouldTrackCodeMessage({ type: 'code', role: 'assistant', format: 'html' })).toBe(false);
    });

    test('false for non-code message', () => {
        expect(shouldTrackCodeMessage({ type: 'message', role: 'assistant' })).toBe(false);
    });
});

describe('shouldTriggerInspectionIndicator', () => {
    // Regression: the check used to be at chunk.start when content was empty → never fired.
    // It must fire at chunk.end when the full code is assembled in message.content.

    const endChunk = { end: true };
    const startChunk = { start: true };
    const midChunk = {};

    test('true at chunk.end when message has inspect_and_report', () => {
        const msg = { type: 'code', content: "_ir = inspect_and_report(file_paths=['/f.tsv'], session_id='s')" };
        expect(shouldTriggerInspectionIndicator(endChunk, msg)).toBe(true);
    });

    test('true at chunk.end when message has inspect_file', () => {
        const msg = { type: 'code', content: "r = inspect_file('/app/static/f.tsv')" };
        expect(shouldTriggerInspectionIndicator(endChunk, msg)).toBe(true);
    });

    test('false at chunk.start — content not yet assembled (regression guard)', () => {
        // This is the exact bug: start chunk has empty content.
        const msg = { type: 'code', content: '' };
        expect(shouldTriggerInspectionIndicator(startChunk, msg)).toBe(false);
    });

    test('false at mid chunk even if content partially assembled', () => {
        const msg = { type: 'code', content: "_ir = inspect_and_report(" };
        expect(shouldTriggerInspectionIndicator(midChunk, msg)).toBe(false);
    });

    test('false at chunk.end for code without inspect calls', () => {
        const msg = { type: 'code', content: 'import pandas as pd\ndf = pd.read_csv("f.csv")' };
        expect(shouldTriggerInspectionIndicator(endChunk, msg)).toBe(false);
    });

    test('false for non-code message type', () => {
        const msg = { type: 'message', content: 'inspect_and_report is mentioned here' };
        expect(shouldTriggerInspectionIndicator(endChunk, msg)).toBe(false);
    });

    test('false when chunk is null', () => {
        const msg = { type: 'code', content: '_ir = inspect_and_report(...)' };
        expect(shouldTriggerInspectionIndicator(null, msg)).toBe(false);
    });

    test('false when message is null', () => {
        expect(shouldTriggerInspectionIndicator(endChunk, null)).toBe(false);
    });
});
