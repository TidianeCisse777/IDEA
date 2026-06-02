const fs = require('fs');
const path = require('path');

describe('assistant message persistence', () => {
    test('saveCompletedAssistantMessage preserves deliverable message type', () => {
        const source = fs.readFileSync(
            path.join(__dirname, '../assistant.js'),
            'utf8'
        );
        const match = source.match(
            /function saveCompletedAssistantMessage[\s\S]*?function createImageMessageFromChunk/
        );

        expect(match).not.toBeNull();
        expect(match[0]).toMatch(
            /const validTypes = \[[^\]]*['"]deliverable['"][^\]]*\]/
        );
    });
});
