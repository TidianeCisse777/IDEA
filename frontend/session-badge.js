// session-badge.js — renders the full session id in the chat header

function updateSessionIdentityBadge(sessionId) {
    const badge = document.getElementById('sessionIdBadge');
    const value = document.getElementById('sessionIdLabel');
    if (!badge || !value) return;

    const id = String(sessionId || '').trim();
    const display = id || '—';

    value.textContent = display;
    badge.title = `Session complète: ${display}`;
    badge.setAttribute('aria-label', `Identifiant complet de session: ${display}`);
}

if (typeof window !== 'undefined') {
    window.updateSessionIdentityBadge = updateSessionIdentityBadge;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { updateSessionIdentityBadge };
}
