/**
 * @jest-environment jsdom
 */

global.sessionId = 'session-test';

const { buildAttachmentInstruction } = require('../file-upload.js');

describe('buildAttachmentInstruction', () => {
    test('states the session-wide duplicate filename rule explicitly', () => {
        const instruction = buildAttachmentInstruction([
            {
                name: 'sample.csv',
                path: 'sample.csv',
                mimeType: 'text/csv',
            },
        ]);

        expect(instruction).toContain('Files uploaded in this message:');
        expect(instruction).toContain('Session rule: compare each filename against filenames already present in this session.');
        expect(instruction).toContain('If a filename already exists, skip its inspection');
    });
});
