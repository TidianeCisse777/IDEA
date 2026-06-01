// session-badge.js — renders the full session id in the chat header

let copyResetTimer = null;

function fallbackCopyText(text) {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', 'true');
    textarea.style.position = 'fixed';
    textarea.style.opacity = '0';
    textarea.style.pointerEvents = 'none';
    document.body.appendChild(textarea);
    textarea.select();
    try {
        document.execCommand('copy');
    } finally {
        document.body.removeChild(textarea);
    }
}

async function copySessionIdentityBadge(sessionId) {
    const id = String(sessionId || '').trim();
    if (!id) return false;

    try {
        if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
            await navigator.clipboard.writeText(id);
        } else {
            fallbackCopyText(id);
        }
    } catch (error) {
        console.error('Failed to copy session id:', error);
        return false;
    }

    const badge = document.getElementById('sessionIdBadge');
    if (badge) {
        badge.title = `Copié: ${id}`;
        badge.setAttribute('aria-label', `Identifiant complet de session copié: ${id}`);
    }

    if (copyResetTimer) {
        clearTimeout(copyResetTimer);
    }
    copyResetTimer = setTimeout(() => {
        const currentBadge = document.getElementById('sessionIdBadge');
        if (currentBadge) {
            currentBadge.title = `Session complète: ${id}`;
            currentBadge.setAttribute('aria-label', `Identifiant complet de session: ${id}`);
        }
    }, 1200);

    return true;
}

function bindSessionIdentityBadgeInteraction() {
    const badge = document.getElementById('sessionIdBadge');
    if (!badge || badge.dataset.copyBound === 'true') return;

    badge.dataset.copyBound = 'true';
    badge.setAttribute('role', 'button');
    badge.setAttribute('tabindex', '0');
    badge.setAttribute('aria-keyshortcuts', 'Enter Space');
    badge.title = badge.title || 'Session complète';

    const handleActivate = (event) => {
        if (event.type === 'keydown' && !['Enter', ' '].includes(event.key)) {
            return;
        }
        event.preventDefault();
        const currentSessionId = badge.dataset.sessionId || document.getElementById('sessionIdLabel')?.textContent || '';
        copySessionIdentityBadge(currentSessionId);
    };

    badge.addEventListener('click', handleActivate);
    badge.addEventListener('keydown', handleActivate);
}

function updateSessionIdentityBadge(sessionId) {
    const badge = document.getElementById('sessionIdBadge');
    const value = document.getElementById('sessionIdLabel');
    if (!badge || !value) return;

    const id = String(sessionId || '').trim();
    const display = id || '—';

    badge.dataset.sessionId = id;
    value.textContent = display;
    badge.title = `Session complète: ${display}`;
    badge.setAttribute('aria-label', `Identifiant complet de session: ${display}`);
    bindSessionIdentityBadgeInteraction();
}

if (typeof window !== 'undefined') {
    window.updateSessionIdentityBadge = updateSessionIdentityBadge;
    window.copySessionIdentityBadge = copySessionIdentityBadge;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = { updateSessionIdentityBadge, copySessionIdentityBadge };
}
