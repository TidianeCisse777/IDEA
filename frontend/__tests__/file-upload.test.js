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
        expect(instruction).toContain('Session rule: for every filename without a report in latest_inspection_by_file, call inspect_and_report immediately.');
        expect(instruction).toContain('If a filename already has a report in latest_inspection_by_file, skip its inspection');
        expect(instruction).toContain('If a filename is pending in active_files without a report, inspect it now in the same turn');
        expect(instruction).not.toContain('explicitly say it is already inspected');
    });
});
