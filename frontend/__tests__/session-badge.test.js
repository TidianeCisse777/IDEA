/**
 * @jest-environment jsdom
 */

const { updateSessionIdentityBadge } = require('../session-badge.js');

function buildDOM() {
    document.body.innerHTML = `
        <div id="sessionIdBadge" class="session-id-badge">
            <span class="session-id-badge-label">Session</span>
            <span id="sessionIdLabel" class="session-id-badge-value">—</span>
        </div>
    `;
}

describe('session-badge', () => {
    beforeEach(() => {
        buildDOM();
        Object.assign(navigator, {
            clipboard: {
                writeText: jest.fn(() => Promise.resolve()),
            },
        });
        document.execCommand = jest.fn(() => true);
    });

    test('renders the full session id in the header badge', () => {
        const sessionId = 'session-abc123xyz-very-long-session-id';
        updateSessionIdentityBadge(sessionId);

        expect(document.getElementById('sessionIdLabel').textContent).toBe(sessionId);
        expect(document.getElementById('sessionIdBadge').title).toContain(sessionId);
        expect(document.getElementById('sessionIdBadge').getAttribute('aria-label')).toContain(sessionId);
    });

    test('falls back to a placeholder when the session id is empty', () => {
        updateSessionIdentityBadge('');

        expect(document.getElementById('sessionIdLabel').textContent).toBe('—');
        expect(document.getElementById('sessionIdBadge').title).toContain('—');
    });

    test('clicking the badge copies the full session id', async () => {
        const sessionId = 'session-abc123xyz-very-long-session-id';
        updateSessionIdentityBadge(sessionId);

        document.getElementById('sessionIdBadge').click();
        await Promise.resolve();

        expect(navigator.clipboard.writeText).toHaveBeenCalledWith(sessionId);
        expect(document.getElementById('sessionIdBadge').title).toContain('Copié');
    });
});
