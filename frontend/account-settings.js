// account-settings.js - Modal behavior for Account Settings and password change

(function() {
    function getEndpoints() {
        try { return config.getEndpoints(); } catch { return {}; }
    }

    function getSessionHeaders() {
        const sessionId = localStorage.getItem('sessionId') || '';
        return {
            'X-Session-Id': sessionId,
            'X-Agent-Type': 'copepod',
        };
    }

    function attachEvents() {
        const modal = document.getElementById('accountSettingsModal');
        const openBtn = document.getElementById('accountSettingsButton');
        const openBtnMobile = document.getElementById('accountSettingsButtonMobile');
        const closeBtn = document.getElementById('closeAccountSettingsModal');
        const cancelBtn = document.getElementById('cancelAccountSettingsBtn');
        const form = document.getElementById('accountSettingsForm');
        const currentEl = document.getElementById('currentPasswordInput');
        const newEl = document.getElementById('newPasswordInput');
        const confirmEl = document.getElementById('confirmPasswordInput');
        const messageEl = document.getElementById('accountSettingsMessage');
        const onlineModeToggle = document.getElementById('onlineModeToggle');

        if (openBtn) openBtn.addEventListener('click', () => {
            ModalUtils.open(modal);
            loadUserProfile();
            loadOnlineMode();
        });
        if (openBtnMobile) openBtnMobile.addEventListener('click', () => {
            ModalUtils.open(modal);
            loadUserProfile();
            loadOnlineMode();
            const navbarMobileMenu = document.getElementById('navbarMobileMenu');
            const navbarToggle = document.getElementById('navbarToggle');
            const mobileOverlay = document.getElementById('mobileOverlay');
            if (navbarMobileMenu) navbarMobileMenu.classList.remove('active');
            if (navbarToggle) navbarToggle.classList.remove('active');
            if (mobileOverlay) mobileOverlay.classList.remove('active');
            document.body.style.overflow = '';
        });
        if (closeBtn) closeBtn.addEventListener('click', () => ModalUtils.close(modal));
        if (cancelBtn) cancelBtn.addEventListener('click', () => ModalUtils.close(modal));

        ModalUtils.bindDismiss(modal, () => ModalUtils.close(modal));

        if (onlineModeToggle) {
            onlineModeToggle.addEventListener('change', async () => {
                await persistOnlineMode(onlineModeToggle.checked);
            });
        }

        if (form) {
            form.addEventListener('submit', async (e) => {
                e.preventDefault();
                if (messageEl) { messageEl.textContent = ''; messageEl.className = 'form-message'; }

                const currentPassword = currentEl?.value?.trim() || '';
                const newPassword = newEl?.value?.trim() || '';
                const confirmPassword = confirmEl?.value?.trim() || '';

                if (!currentPassword || !newPassword || !confirmPassword) {
                    setMessage('All fields are required.', 'error');
                    return;
                }
                if (newPassword.length < 8 || newPassword.length > 40) {
                    setMessage('New password must be 8-40 characters.', 'error');
                    return;
                }
                if (newPassword !== confirmPassword) {
                    setMessage('New passwords do not match.', 'error');
                    return;
                }

                try {
                    const endpoints = getEndpoints();
                    const url = endpoints.changePassword || '/api/users/change-password';
                    const res = await fetch(url, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            ...Auth.getAuthHeaders()
                        },
                        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
                    });

                    if (!res.ok) {
                        let detail = 'Failed to change password';
                        try { const err = await res.json(); if (err && err.detail) detail = err.detail; } catch {}
                        throw new Error(detail);
                    }

                    setMessage('Password updated successfully.', 'success');
                    if (currentEl) currentEl.value = '';
                    if (newEl) newEl.value = '';
                    if (confirmEl) confirmEl.value = '';
                } catch (err) {
                    setMessage(err.message || 'Failed to change password', 'error');
                }
            });
        }

        function setMessage(text, type) {
            if (!messageEl) return;
            messageEl.textContent = text;
            messageEl.className = `form-message ${type}`;
        }

        async function loadUserProfile() {
            const userEmailDisplay = document.getElementById('userEmailDisplay');
            if (!userEmailDisplay) return;

            try {
                const endpoints = getEndpoints();
                const url = endpoints.userProfile || '/api/users/me';
                const res = await fetch(url, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                        ...Auth.getAuthHeaders()
                    }
                });

                if (res.ok) {
                    const userProfile = await res.json();
                    userEmailDisplay.value = userProfile.email || '';
                } else {
                    console.error('Failed to load user profile');
                    userEmailDisplay.value = 'Unable to load email';
                }
            } catch (err) {
                console.error('Error loading user profile:', err);
                userEmailDisplay.value = 'Unable to load email';
            }
        }

        function setOnlineModeUi(enabled, allowedSources) {
            const badge = document.getElementById('onlineModeBadge');
            const label = document.getElementById('onlineModeLabel');
            const allowed = document.getElementById('onlineModeAllowedSources');
            const toggle = document.getElementById('onlineModeToggle');
            if (toggle) toggle.checked = Boolean(enabled);
            if (badge) badge.style.display = 'flex';
            if (label) label.textContent = `Mode En Ligne: ${enabled ? 'ON' : 'OFF'}`;
            if (allowed) {
                allowed.textContent = Array.isArray(allowedSources) && allowedSources.length
                    ? allowedSources.join(', ')
                    : 'Aucune source autorisée';
            }
        }

        async function loadOnlineMode() {
            const endpoints = getEndpoints();
            const url = endpoints.onlineMode || '/api/session/online-mode';
            try {
                const res = await fetch(url, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                        ...getSessionHeaders(),
                        ...Auth.getAuthHeaders(),
                    },
                });

                if (!res.ok) {
                    throw new Error('Failed to load online mode');
                }

                const payload = await res.json();
                setOnlineModeUi(payload.enabled, payload.allowed_sources || []);
            } catch (err) {
                console.error('Error loading online mode:', err);
            }
        }

        async function persistOnlineMode(enabled) {
            const endpoints = getEndpoints();
            const url = endpoints.onlineMode || '/api/session/online-mode';
            try {
                const res = await fetch(url, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json',
                        ...getSessionHeaders(),
                        ...Auth.getAuthHeaders(),
                    },
                    body: JSON.stringify({ enabled }),
                });

                if (!res.ok) {
                    throw new Error('Failed to persist online mode');
                }

                const payload = await res.json();
                setOnlineModeUi(payload.enabled, payload.allowed_sources || []);
            } catch (err) {
                console.error('Error saving online mode:', err);
                setMessage(err.message || 'Failed to update online mode', 'error');
                if (onlineModeToggle) {
                    onlineModeToggle.checked = !enabled;
                }
            }
        }
    }

    document.addEventListener('DOMContentLoaded', attachEvents);
})();
